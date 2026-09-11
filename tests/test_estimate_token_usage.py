"""crawl estimate-token-usage <analysis> <repo_path>: the pre-flight file-crawl
preview (coderay-05w.1).

Every analysis exposes preview(args), which runs only its crawl step -- pure
filesystem work, no LLM call -- and reports what that crawl counted. The counts
are not uniform across analyses: each crawler tracks what its own bundle needs,
and preview reports that rather than a common triple it would have to invent.
"""
import argparse
import importlib
import os
import subprocess
import sys

import pytest

import crawl.core.llm as llm_module
from crawl.analyses import ANALYSES

ANALYSIS_NAMES = sorted(ANALYSES)


def _env(tmp_path, **extra):
    """A subprocess environment with every knob this project reads cleared, so a
    developer's shell cannot leak in. No API key: the preview must run without one."""
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "config"))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "LLM_PROVIDER", "CODEBASE_BUDGET"):
        env.pop(var, None)
    env.update(extra)
    return env


def _repo(tmp_path):
    """One repo every analysis finds something in: a git checkout with a backend
    route, a model, a schema, a manifest and a compose file. git-history needs a
    real checkout, and repo_root refuses a subdirectory, so this is its own root."""
    repo = tmp_path / "sample_repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "views.py").write_text(
        "def index(request):\n    return render(request, 'i.html')\n", encoding="utf-8")
    (repo / "app" / "models.py").write_text(
        "class User(Model):\n    name = CharField()\n", encoding="utf-8")
    (repo / "app" / "urls.py").write_text(
        "urlpatterns = [path('', index)]\n", encoding="utf-8")
    (repo / "schema.sql").write_text(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT);\n", encoding="utf-8")
    (repo / "package.json").write_text('{"dependencies": {"express": "^4"}}\n', encoding="utf-8")
    (repo / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: python\n", encoding="utf-8")

    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Tester")
    run("add", "-A")
    run("commit", "-qm", "first commit")
    return repo


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_every_analysis_exposes_a_preview_callable(name):
    assert callable(getattr(ANALYSES[name], "preview", None)), \
        f"{name} has no preview(args); estimate-token-usage cannot reach its crawl step"


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_preview_reports_counts_and_the_files_behind_them(tmp_path, name):
    repo = _repo(tmp_path)
    parser = _parser_for(name)
    result = ANALYSES[name].preview(parser.parse_args([str(repo)]))

    assert set(result) == {"counts", "files", "notes"}
    assert result["counts"], f"{name} reported no counts at all"
    assert all(isinstance(v, int) for v in result["counts"].values()), \
        f"{name} put a non-count in counts: {result['counts']}"
    assert all(isinstance(v, list) for v in result["files"].values()), \
        f"{name} put a non-list in files: {list(result['files'])}"
    assert all(isinstance(n, str) for n in result["notes"]), \
        f"{name} put a non-string in notes: {result['notes']}"
    # Every analysis finds something in this repo, so an all-zero report means
    # the preview never reached its crawl step.
    assert any(v > 0 for v in result["counts"].values()), \
        f"{name} found nothing in a repo built for all seven: {result['counts']}"


def _parser_for(name):
    parser = argparse.ArgumentParser(prog=f"estimate-token-usage {name}")
    parser.add_argument("repo_path")
    ANALYSES[name].add_arguments(parser)
    return parser


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_preview_makes_no_llm_call(tmp_path, name, monkeypatch):
    """The whole point of the preview: it is free. A call_llm that raises proves
    no path reached the model, whichever of the two import seams it would use."""
    def refuse(*a, **kw):
        raise AssertionError(f"{name}'s preview called the LLM")

    monkeypatch.setattr(llm_module, "call_llm", refuse)
    # crawl.core re-exports call_llm the function, shadowing the module of the
    # same name, so `import crawl.core.call_llm as x` binds the function.
    monkeypatch.setattr(importlib.import_module("crawl.core.call_llm"), "call_llm", refuse)

    ANALYSES[name].preview(_parser_for(name).parse_args([str(_repo(tmp_path))]))


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_dispatches_without_an_api_key(tmp_path, name):
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert name in result.stdout


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_writes_nothing(tmp_path, name):
    repo = _repo(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    before = sorted(p.name for p in repo.iterdir())

    subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), cwd=str(cwd), check=True,
    )

    assert sorted(p.name for p in repo.iterdir()) == before
    assert list(cwd.iterdir()) == [], "estimate-token-usage wrote an output directory"


def test_estimate_token_usage_rejects_an_out_flag(tmp_path):
    """Nothing is written, so --out has no meaning here and must not be accepted
    silently -- a user passing it is expecting a file that will never appear."""
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "tour", str(repo),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 2
    assert "--out" in result.stderr


def test_codebase_budget_reaches_the_crawl_step(tmp_path):
    """The estimate must reflect the exact flags a real run would use. A budget
    small enough to spend on the first file drops the rest (product-intent is the
    one crawler that counts drops outright)."""
    repo = _repo(tmp_path)
    parser = _parser_for("product-intent")

    generous = ANALYSES["product-intent"].preview(parser.parse_args([str(repo)]))
    tiny = ANALYSES["product-intent"].preview(
        parser.parse_args([str(repo), "--codebase-budget", "200"]))

    assert tiny["counts"]["dropped"] > 0
    assert tiny["counts"]["included"] < generous["counts"]["included"]


def test_exclude_reaches_the_crawl_step(tmp_path):
    """product-intent's own --exclude, honoured the same way --codebase-budget is."""
    repo = _repo(tmp_path)
    parser = _parser_for("product-intent")

    everything = ANALYSES["product-intent"].preview(parser.parse_args([str(repo)]))
    filtered = ANALYSES["product-intent"].preview(
        parser.parse_args([str(repo), "--exclude", "*.py"]))

    assert filtered["counts"]["included"] < everything["counts"]["included"]
    assert not any(f.endswith(".py") for f in filtered["files"]["included"])


def test_schema_override_reaches_the_crawl_step(tmp_path):
    """schema's own --schema flag, the analysis-specific one the epic names."""
    repo = _repo(tmp_path)
    (repo / "other.sql").write_text(
        "CREATE TABLE posts (id INT PRIMARY KEY);\n", encoding="utf-8")
    parser = _parser_for("schema")

    picked = ANALYSES["schema"].preview(
        parser.parse_args([str(repo), "--schema", "other.sql"]))

    assert picked["files"]["schema"] == ["other.sql"]


def test_git_history_reports_commits_not_files(tmp_path):
    """git-history has no file counts. Eras are LLM output and cannot appear in a
    no-LLM preview, so the preview reports the log it actually read."""
    repo = _repo(tmp_path)
    result = ANALYSES["git-history"].preview(_parser_for("git-history").parse_args([str(repo)]))

    assert result["counts"]["commits"] == 1
    assert "eras" not in result["counts"]


def test_git_history_warns_that_a_shallow_clones_commit_count_is_a_fragment(tmp_path):
    """A shallow clone's commit count is not the repo's history. Reporting the
    number without saying so states a falsehood (coderay-q2r.38)."""
    origin = _repo(tmp_path)
    for extra in ("second", "third"):
        (origin / f"{extra}.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(origin), "commit", "-qm", extra], check=True, capture_output=True)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
                   check=True, capture_output=True)

    result = ANALYSES["git-history"].preview(_parser_for("git-history").parse_args([str(shallow)]))

    assert any("shallow" in note for note in result["notes"])


def test_preview_reports_zero_rather_than_aborting_on_an_empty_repo(tmp_path):
    """A real run raises SystemExit when a crawl finds nothing, because three paid
    passes over nothing would invent an answer. A preview has nothing to protect:
    reporting zero is the useful answer, and it is what the user came to find out."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    (repo / "README.md").write_text("nothing here\n", encoding="utf-8")

    result = ANALYSES["backend"].preview(_parser_for("backend").parse_args([str(repo)]))

    assert result["counts"]["included"] == 0


def test_estimate_token_usage_reports_the_counts_on_stdout(tmp_path):
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "product-intent", str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), check=True,
    )
    assert "included" in result.stdout
    assert "dropped" in result.stdout
    assert "unreadable" in result.stdout


# The budget reaches every crawl step, but what it does there differs: these
# crawlers drop whole files, so the counts move. schema and architecture cap
# text instead (see the two tests below), and tour's file preview is sized by a
# different budget entirely.
@pytest.mark.parametrize("name", ["backend", "interfaces", "product-intent"])
def test_codebase_budget_changes_the_counts(tmp_path, name):
    repo = _repo(tmp_path)
    parser = _parser_for(name)

    generous = ANALYSES[name].preview(parser.parse_args([str(repo)]))
    tiny = ANALYSES[name].preview(parser.parse_args([str(repo), "--codebase-budget", "1"]))

    assert tiny["counts"] != generous["counts"]


def test_schema_budget_drops_whole_model_files(tmp_path):
    """A schema spread over several models.py files is joined under the budget,
    whole blocks and fewer of them, so the budget moves the file count."""
    repo = tmp_path / "django_repo"
    for app in ("users", "posts", "billing"):
        (repo / app).mkdir(parents=True)
        (repo / app / "models.py").write_text(
            f"class {app.title()}(Model):\n    name = CharField()\n" * 20, encoding="utf-8")
    parser = _parser_for("schema")

    generous = ANALYSES["schema"].preview(parser.parse_args([str(repo)]))
    tiny = ANALYSES["schema"].preview(parser.parse_args([str(repo), "--codebase-budget", "400"]))

    assert generous["counts"]["schema files"] > 1
    assert tiny["counts"]["schema files"] < generous["counts"]["schema files"]


def test_architecture_notes_a_truncated_bundle(tmp_path):
    """This crawler caps the assembled text rather than dropping files, so the
    counts alone would overstate what the model actually reads."""
    repo = _repo(tmp_path)
    parser = _parser_for("architecture")

    tiny = ANALYSES["architecture"].preview(parser.parse_args([str(repo), "--codebase-budget", "1"]))

    assert any("truncated" in note for note in tiny["notes"])


def test_tour_file_preview_is_not_sized_by_the_codebase_budget(tmp_path):
    """tour's crawl step builds the file-selection prompt, which preview_budget
    caps. --codebase-budget sizes the later analyze/relate/chapter prompts, which
    no file-crawl preview reaches; the token estimate is where it shows up."""
    repo = _repo(tmp_path)
    parser = _parser_for("tour")

    generous = ANALYSES["tour"].preview(parser.parse_args([str(repo)]))
    tiny = ANALYSES["tour"].preview(parser.parse_args([str(repo), "--codebase-budget", "1"]))

    assert tiny["counts"] == generous["counts"]


def test_tour_preview_lists_the_files_whose_head_goes_to_the_model(tmp_path):
    repo = _repo(tmp_path)
    result = ANALYSES["tour"].preview(_parser_for("tour").parse_args([str(repo)]))

    assert result["counts"]["previewed"] == len(result["files"]["previewed"])
    assert "app/views.py" in result["files"]["previewed"]
