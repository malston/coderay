"""crawl estimate-token-usage <analysis> <repo_path>: the pre-flight file-crawl
preview (coderay-05w.1).

Every analysis exposes preview(args), which runs only its crawl step -- no LLM
call and no network, filesystem and local git only -- and reports what that crawl
counted. The counts are not uniform across analyses: each crawler tracks what its
own bundle needs, and preview reports that rather than a common triple it would
have to invent.
"""
import argparse
import os
import pathlib
import subprocess
import sys

import pytest

from crawl.analyses import ANALYSES
from crawl.analyses.tour import nodes as tour_nodes
from crawl.core import files
from crawl.core import get_usage, reset_usage

ANALYSIS_NAMES = sorted(ANALYSES)

# Analyses whose crawl step aborts a real run when it finds nothing to send.
ABORTS_WHEN_EMPTY = ["architecture", "backend", "interfaces", "product-intent", "schema"]


@pytest.fixture(autouse=True)
def _no_budget_from_the_shell(monkeypatch):
    """codebase_budget_argument reads CODEBASE_BUDGET when the parser is BUILT,
    so a developer's shell reaches every in-process test through _parser_for.
    _env already clears it for the subprocess tests."""
    monkeypatch.delenv("CODEBASE_BUDGET", raising=False)


def _env(tmp_path, **extra):
    """A subprocess environment with every knob this project reads cleared, so a
    developer's shell cannot leak in. No API key: the preview must run without one.

    HOME and both XDG roots point inside tmp_path, so "wrote nothing" can be
    checked rather than assumed -- otherwise a write into the real ~/.cache/crawl
    is invisible to any assertion the test can make."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home),
               XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"))
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
    """The whole point of the preview: it is free.

    Patching the name is not enough -- every nodes module does `from crawl.core
    import call_llm` at import time, so seven module namespaces hold their own
    binding and a patch on one of them routes around none of the others. The
    usage ledger is the seam no import can bypass: _record_usage fires inside
    call_llm itself, on the disk-cache-hit path as well as the live one, so a
    cached reply is caught the same as a paid one. Keys are scrubbed too, so a
    stray call on a developer's machine cannot quietly spend money."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    reset_usage()

    ANALYSES[name].preview(_parser_for(name).parse_args([str(_repo(tmp_path))]))

    assert get_usage() == [], f"{name}'s preview reached the model"


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_dispatches_without_an_api_key(tmp_path, name):
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    # Not just the header: one label from this analysis's own count set, so
    # swapping two entries in the dispatch table cannot pass.
    expected = ANALYSES[name].preview(_parser_for(name).parse_args([str(repo)]))
    label = next(iter(expected["counts"]))
    assert f"{name}: " in result.stdout
    assert label[0].upper() + label[1:] in result.stdout


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_writes_nothing(tmp_path, name):
    repo = _repo(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = _env(tmp_path)
    home = pathlib.Path(env["HOME"])
    walk = lambda root: sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    before_repo, before_home = walk(repo), walk(home)

    subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(repo)],
        capture_output=True, text=True, env=env, cwd=str(cwd), check=True,
    )

    # Recursive, not iterdir: a write into repo/app/ or repo/.git/ is still a write.
    assert walk(repo) == before_repo, "estimate-token-usage wrote into the target repo"
    assert walk(home) == before_home, "estimate-token-usage wrote into the user's home"
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

    assert tiny["counts"]["dropped by the budget"] > 0
    assert tiny["counts"]["files in the bundle"] < generous["counts"]["files in the bundle"]


def test_exclude_reaches_the_crawl_step(tmp_path):
    """product-intent's own --exclude, honoured the same way --codebase-budget is."""
    repo = _repo(tmp_path)
    parser = _parser_for("product-intent")

    everything = ANALYSES["product-intent"].preview(parser.parse_args([str(repo)]))
    filtered = ANALYSES["product-intent"].preview(
        parser.parse_args([str(repo), "--exclude", "*.py"]))

    assert filtered["counts"]["files in the bundle"] < everything["counts"]["files in the bundle"]
    assert not any(f.endswith(".py") for f in filtered["files"]["bundle"])


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
    assert result["counts"]["bulk additions (10+ files)"] == 0
    assert result["files"] == {}


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

    assert result["counts"]["files in the bundle"] == 0


def test_estimate_token_usage_reports_the_counts_on_stdout(tmp_path):
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "product-intent", str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), check=True,
    )
    assert "Files in the bundle" in result.stdout
    assert "Dropped by the budget" in result.stdout
    assert "Unreadable" in result.stdout


# The budget reaches every crawl step, but what it does there differs. These
# three drop whole files on every path, so their counts always move. schema is
# excluded because its count moves only for a multi-file schema (the test below
# builds one); architecture is excluded because it caps assembled text instead;
# and tour's file preview is sized by a different budget entirely.
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

    assert generous["counts"]["schema files read"] > 1
    assert tiny["counts"]["schema files read"] < generous["counts"]["schema files read"]


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

    assert "app/views.py" in result["files"]["previewed"]


# ---------------------------------------------------------------- path guards

@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_refuses_a_path_that_does_not_exist(tmp_path, name):
    """Every run() guards the path. Without the same guard here, os.walk swallows
    the OSError and a typo reports the same clean zeros as an empty repo."""
    missing = tmp_path / "no-such-repo"
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(missing)],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 1
    assert "is not a directory" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_estimate_token_usage_refuses_a_file_where_a_directory_belongs(tmp_path, name):
    plain = tmp_path / "a_file.py"
    plain.write_text("x = 1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", name, str(plain)],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 1
    assert "is not a directory" in result.stderr


def test_git_history_preview_refuses_a_subdirectory(tmp_path):
    """git -C walks up to the enclosing .git, so a subdirectory would be previewed
    as its parent, under the wrong name (coderay-q2r.38). The real run refuses it;
    an estimate that does not predicts a run that will never start."""
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "git-history",
         str(repo / "app")],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 1
    assert "not the root of a git repository" in result.stderr
    assert "Traceback" not in result.stderr


def test_git_history_preview_refuses_a_directory_that_is_not_a_checkout(tmp_path):
    plain = tmp_path / "not_a_checkout"
    plain.mkdir()
    (plain / "main.py").write_text("x = 1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "git-history", str(plain)],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_schema_preview_reports_nothing_read_when_the_named_schema_is_missing(tmp_path):
    """find_schema names the file before it reads it, so a --schema path that does
    not exist comes back with files=[rel] and text="". Counting the name would
    assert the opposite of the truth. The same refusal covers a symlink whose
    target is credential-named (coderay-q2r.56)."""
    repo = _repo(tmp_path)
    result = ANALYSES["schema"].preview(
        _parser_for("schema").parse_args([str(repo), "--schema", "does/not/exist.prisma"]))

    assert result["counts"]["schema files read"] == 0
    assert result["files"]["schema"] == []
    assert any("could not be read" in note for note in result["notes"])


# ------------------------------------------------------- what the counts mean

def test_tour_preview_reports_what_the_preview_cap_dropped(tmp_path):
    """SmartCrawl reads only preview_budget // PREVIEW_CHARS_PER_FILE files into
    the selection prompt. Reporting the capped number alone hides every file the
    model will never see, and the cap is the whole reason a large repo's estimate
    is wrong."""
    repo = tmp_path / "wide_repo"
    repo.mkdir()
    for i in range(12):
        (repo / f"mod_{i:02d}.py").write_text(f"VALUE = {i}\n", encoding="utf-8")
    parser = _parser_for("tour")

    result = ANALYSES["tour"].preview(parser.parse_args([str(repo)]))
    assert result["counts"]["source files found"] == 12
    assert result["counts"]["read into the selection pass"] == 12
    assert result["counts"]["dropped before the model saw them"] == 0
    assert result["notes"] == []


def test_tour_preview_notes_the_files_the_model_will_never_see(tmp_path, monkeypatch):
    repo = tmp_path / "wide_repo"
    repo.mkdir()
    for i in range(12):
        (repo / f"mod_{i:02d}.py").write_text(f"VALUE = {i}\n", encoding="utf-8")
    monkeypatch.setattr(tour_nodes, "PREVIEW_CHARS_PER_FILE", 200_000)  # fits 5 files

    result = ANALYSES["tour"].preview(_parser_for("tour").parse_args([str(repo)]))

    assert result["counts"]["source files found"] == 12
    assert result["counts"]["read into the selection pass"] == 5
    assert result["counts"]["dropped before the model saw them"] == 7
    assert any("never reach" in note for note in result["notes"])


def test_architecture_bundle_count_and_bundle_list_agree(tmp_path):
    """The config-file count and the bundle list describe different populations:
    the list carries env files and dependency manifests too. Reporting the list's
    own length beside it keeps the pair from contradicting each other under
    --verbose (coderay-05w.3)."""
    repo = _repo(tmp_path)
    parser = _parser_for("architecture")

    for argv in ([str(repo)], [str(repo), "--codebase-budget", "60"]):
        result = ANALYSES["architecture"].preview(parser.parse_args(argv))
        assert result["counts"]["files in the bundle"] == len(result["files"]["bundle"])


def test_architecture_preview_reports_the_two_largest_drivers_of_bundle_size(tmp_path):
    """The node's post() reports env_vars and sdk_lines; a preview that drops them
    describes a smaller bundle than the run will build."""
    repo = _repo(tmp_path)
    result = ANALYSES["architecture"].preview(_parser_for("architecture").parse_args([str(repo)]))

    assert "env var names" in result["counts"]
    assert "SDK import lines" in result["counts"]


def test_architecture_note_carries_why_sdk_evidence_is_unavailable(tmp_path):
    """sdk_unavailable is a reason, not a flag: 'not a git repository' and 'git is
    not installed' are different problems and only one is the user's to fix."""
    repo = tmp_path / "not_a_checkout"
    repo.mkdir()
    (repo / "package.json").write_text('{"dependencies": {"express": "^4"}}\n', encoding="utf-8")

    result = ANALYSES["architecture"].preview(_parser_for("architecture").parse_args([str(repo)]))

    assert any("not a git repository" in note for note in result["notes"])


def test_interfaces_preview_notes_surface_files_it_could_not_read(tmp_path):
    repo = _repo(tmp_path)
    result = ANALYSES["interfaces"].preview(
        _parser_for("interfaces").parse_args([str(repo), "--codebase-budget", "1"]))

    assert result["counts"]["surface files found"] > result["counts"]["surface files read"]
    assert any("did not reach the bundle" in note for note in result["notes"])


def test_schema_preview_notes_a_truncated_schema(tmp_path):
    """A 5MB schema and a 3KB one both read as one file. For a command about token
    usage the truncation is the headline, not a footnote."""
    repo = tmp_path / "big_schema"
    repo.mkdir()
    (repo / "schema.sql").write_text("CREATE TABLE t (id INT);\n" * 400, encoding="utf-8")

    result = ANALYSES["schema"].preview(
        _parser_for("schema").parse_args([str(repo), "--codebase-budget", "500"]))

    assert any("truncated" in note for note in result["notes"])


def test_git_history_labels_say_what_counts_as_bulk(tmp_path):
    """The two thresholds differ (10 files added, 5 deleted) and are hardcoded in
    the crawl, so the bare labels make two incomparable numbers look comparable."""
    repo = _repo(tmp_path)
    result = ANALYSES["git-history"].preview(_parser_for("git-history").parse_args([str(repo)]))

    assert "bulk additions (10+ files)" in result["counts"]
    assert "bulk deletions (5+ files)" in result["counts"]


@pytest.mark.parametrize("name", ABORTS_WHEN_EMPTY)
def test_preview_says_when_a_real_run_would_abort(tmp_path, name):
    """Reporting zero rather than aborting is right for a preview. Reporting zero
    without saying the real run stops there is the part that leaves the user
    guessing, and every one of these crawls already knows the reason."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()

    result = ANALYSES[name].preview(_parser_for(name).parse_args([str(repo)]))

    assert any(note.startswith("A real run stops here:") for note in result["notes"]), result["notes"]


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_preview_reports_zero_without_aborting_for_every_analysis(tmp_path, name):
    """The deliberate decision, held for all seven rather than just backend."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    (repo / "README.md").write_text("nothing here\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)

    result = ANALYSES[name].preview(_parser_for(name).parse_args([str(repo)]))

    assert all(v >= 0 for v in result["counts"].values())


# ------------------------------------------------------------ the CLI surface

def test_estimate_token_usage_rejects_a_dry_run_flag(tmp_path):
    """--out is refused because nothing is written. --dry-run promises the very
    token estimate this command does not yet produce, so it cannot be accepted
    and ignored two lines away from that refusal."""
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "tour", str(repo), "--dry-run"],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert result.returncode == 2
    assert "--dry-run" in result.stderr


def test_estimate_token_usage_keeps_crawler_progress_off_stdout(tmp_path):
    """The crawlers print progress in-band with a real run's log. stdout here is a
    single formatted report, so that chatter belongs on stderr (coderay-pqj)."""
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "architecture", str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), check=True,
    )
    assert result.stdout.startswith("architecture: ")


def test_estimate_token_usage_says_it_does_not_price_the_run(tmp_path):
    """The command is named for tokens and reports none of them. Saying so beats
    leaving the reader to conclude it is broken."""
    repo = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "backend", str(repo)],
        capture_output=True, text=True, env=_env(tmp_path), check=True,
    )
    assert "tokens" in result.stdout.lower()


def test_analysis_flags_reach_the_crawl_step_through_the_cli(tmp_path):
    """Every other flag test builds its own parser and never touches cli.py, so
    the `analysis.add_arguments(sub)` line itself goes unpinned."""
    repo = _repo(tmp_path)
    run = lambda *extra: subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "product-intent",
         str(repo), *extra],
        capture_output=True, text=True, env=_env(tmp_path), check=True).stdout

    assert run() != run("--codebase-budget", "1")
    assert run() != run("--exclude", "*.py")


def test_git_history_flags_parse_but_do_not_change_the_crawl(tmp_path):
    """All four size the prompts or filter after the crawl; FetchHistory hardcodes
    its own thresholds. The flags must still parse, so the command line matches a
    real run, but a user changing one should not expect these counts to move."""
    repo = _repo(tmp_path)
    run = lambda *extra: subprocess.run(
        [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "git-history",
         str(repo), *extra],
        capture_output=True, text=True, env=_env(tmp_path), check=True).stdout

    assert run() == run("--max-graves", "3", "--grave-min-files", "40",
                        "--profile-max-commits", "9", "--profile-diff-chars", "9")


def test_product_intent_include_reaches_the_crawl_step(tmp_path):
    repo = _repo(tmp_path)
    parser = _parser_for("product-intent")

    only_json = ANALYSES["product-intent"].preview(
        parser.parse_args([str(repo), "--include", "*.json"]))

    assert only_json["files"]["bundle"] == ["package.json"]


# ------------------------------------------------------------------ invariants

@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_preview_lists_only_paths_inside_the_repo(tmp_path, name):
    """list_files refuses a symlink resolving outside the repo (coderay-q2r.16).
    Nothing prints `files` today, but coderay-05w.3 will, so the invariant is
    pinned at the boundary that will carry it."""
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 'hunter2'\n", encoding="utf-8")
    os.symlink(outside, repo / "app" / "linked.py")

    result = ANALYSES[name].preview(_parser_for(name).parse_args([str(repo)]))

    listed = [rel for group in result["files"].values() for rel in group]
    assert not any(rel.startswith("..") or os.path.isabs(rel) for rel in listed), listed
    assert "app/linked.py" not in listed


# architecture is excluded: it reads .env files on purpose, for the variable
# NAMES, and omits every value (arch_crawl._redact). Naming the file it read is
# the point. The other six refuse a credential-named target outright.
@pytest.mark.parametrize("name", [n for n in ANALYSIS_NAMES if n != "architecture"])
def test_preview_never_names_a_credential_file(tmp_path, name):
    """The crawlers refuse credential-named targets and symlinks resolving to one
    (coderay-q2r.56), whether convention found the name or the model asked for it."""
    repo = _repo(tmp_path)
    (repo / ".env").write_text("SECRET_KEY=hunter2\n", encoding="utf-8")
    os.symlink(repo / ".env", repo / "settings_local.py")

    result = ANALYSES[name].preview(_parser_for(name).parse_args([str(repo)]))

    listed = [rel for group in result["files"].values() for rel in group]
    assert not any(rel.endswith(".env") or rel == "settings_local.py" for rel in listed), listed


def test_the_two_agent_docs_describe_the_preview_identically():
    """The convention bullet is duplicated into CLAUDE.md and AGENTS.md, so the
    first edit that touches only one of them silently splits the contract."""
    claude = pathlib.Path("CLAUDE.md").read_text(encoding="utf-8")
    agents = pathlib.Path("AGENTS.md").read_text(encoding="utf-8")
    bullet = lambda text: next(
        line for line in text.splitlines() if line.startswith("- Every analysis declares `preview(args)`"))

    assert bullet(claude) == bullet(agents)


# ------------------------------------------------------- the README's claims

def _readme_preview_section():
    readme = pathlib.Path("README.md").read_text(encoding="utf-8")
    start = readme.index("### Preview what the crawl will read")
    return readme[start:readme.index("### Send the model more of the code", start)]


@pytest.mark.parametrize("name", ANALYSIS_NAMES)
def test_the_readme_names_every_analysis_the_preview_supports(name):
    """The README tabulates what each crawler counts. An eighth analysis, or a
    renamed one, must not leave that table quietly describing six."""
    assert f"`{name}`" in _readme_preview_section()


def test_the_readme_quotes_tours_real_count_labels(tmp_path):
    """The sample output is transcribed, so a renamed label leaves the README
    showing a report the command no longer prints."""
    section = _readme_preview_section()
    result = ANALYSES["tour"].preview(_parser_for("tour").parse_args([str(_repo(tmp_path))]))

    for label in result["counts"]:
        assert label[0].upper() + label[1:] in section, label


def test_the_readme_quotes_the_real_crawl_constants():
    """The three narrowings are explained with numbers. They are constants in the
    code, and the prose is wrong the moment one of them moves."""
    section = _readme_preview_section()

    assert tour_nodes.PREVIEW_CHARS_PER_FILE == 800
    assert f"{tour_nodes.PREVIEW_CHARS_PER_FILE} chars" in section
    assert files.DEFAULT_MAX_FILE_BYTES == 500_000
    assert "500 KB" in section


# ------------------------------------- honesty of what the report claims

def test_tour_does_not_call_its_filtered_count_files_on_disk(tmp_path):
    """list_files has already dropped every unrecognised extension, every skipped
    directory and everything over the size ceiling, so its result is nowhere near
    what is on disk. A reader sizing a run takes the first row as the repo's size."""
    repo = tmp_path / "mixed_repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("module.exports = 1\n", encoding="utf-8")

    result = ANALYSES["tour"].preview(_parser_for("tour").parse_args([str(repo)]))

    assert "files on disk" not in result["counts"]
    assert result["counts"]["source files found"] == 1


def test_tour_says_when_a_real_run_would_abort(tmp_path):
    """tour was the one analysis left without the note. A real run hands
    SmartCrawl an empty file list, and every index the model returns is rejected,
    so yaml_call burns its retries after paid calls."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()

    result = ANALYSES["tour"].preview(_parser_for("tour").parse_args([str(repo)]))

    assert any(note.startswith("A real run stops here:") for note in result["notes"])


def test_git_history_says_when_a_real_run_would_abort(tmp_path):
    repo = tmp_path / "no_commits"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)

    result = ANALYSES["git-history"].preview(_parser_for("git-history").parse_args([str(repo)]))

    assert result["counts"]["commits"] == 0
    assert any(note.startswith("A real run stops here:") for note in result["notes"])


def test_schema_does_not_claim_truncation_when_nothing_was_truncated(tmp_path):
    """The embedded-SQL path reads the Go file with no limit at all, so its text
    routinely runs past the budget without a cut. Sizing that as proof of
    truncation tells the reader the model sees less when it sees several times
    the budget."""
    repo = tmp_path / "go_repo"
    repo.mkdir()
    (repo / "db.go").write_text(
        'package db\n\nconst schema = `\n'
        + "".join(f"CREATE TABLE t{i} (id INT PRIMARY KEY);\n" for i in range(400))
        + '`\n', encoding="utf-8")

    result = ANALYSES["schema"].preview(
        _parser_for("schema").parse_args([str(repo), "--codebase-budget", "2000"]))

    assert not any("truncated" in note for note in result["notes"]), result["notes"]


def test_require_directory_refuses_a_directory_it_cannot_walk(tmp_path):
    """os.path.isdir is True for a directory with no read or execute permission,
    and os.walk then swallows the PermissionError and yields nothing -- the exact
    clean-zeros-on-a-failure the guard exists to prevent."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        if os.access(str(locked), os.R_OK | os.X_OK):
            pytest.skip("running with permission to read a 000 directory (root?)")
        result = subprocess.run(
            [sys.executable, "-m", "crawl.cli", "estimate-token-usage", "tour", str(locked)],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert result.returncode == 1
        assert "cannot be read" in result.stderr
    finally:
        locked.chmod(0o700)
