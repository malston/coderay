import pytest

from crack.analyses.schema import schema_find as sf


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


@pytest.mark.parametrize("rel,kind", [
    ("packages/db/schema.prisma", "prisma"),
    ("db/schema.rb", "rails"),
    ("schema.sql", "sql"),
    ("app/models.py", "models"),
])
def test_find_schema_recognises_each_convention(tmp_path, rel, kind):
    repo = _repo(tmp_path, {rel: "model User {}\n"})
    found = sf.find_schema(repo)
    assert found["kind"] == kind
    assert "model User" in found["text"]


def test_find_schema_prefers_prisma_over_every_other_convention(tmp_path):
    """Priority order matters: a repo can carry several of these at once.

    models.py sorts first alphabetically and schema.sql last, so the order the
    walk happens to produce is not the order the function must return.
    """
    repo = _repo(tmp_path, {
        "app/models.py": "class User(Model): pass\n",
        "db/schema.rb": "create_table :users\n",
        "schema.sql": "CREATE TABLE users();\n",
        "packages/db/schema.prisma": "model User {}\n",
    })
    assert sf.find_schema(repo)["kind"] == "prisma"


def test_find_schema_picks_the_largest_prisma_not_the_first(tmp_path):
    """A package fixture schema must not beat the application's."""
    repo = _repo(tmp_path, {
        "aaa/fixtures/schema.prisma": "model Tiny {}\n",
        "zzz/app/schema.prisma": "model User {}\n" * 50,
    })
    found = sf.find_schema(repo)
    assert found["path"].startswith("zzz/")


def test_find_schema_only_counts_schema_rb_inside_a_db_directory(tmp_path):
    """Rails puts it in db/. A schema.rb elsewhere is something else."""
    repo = _repo(tmp_path, {"lib/schema.rb": "not the rails schema\n"})
    assert sf.find_schema(repo)["kind"] is None


def test_find_schema_concatenates_model_files_when_there_is_no_single_file(tmp_path):
    repo = _repo(tmp_path, {"app/models.py": "class User(Model): pass\n",
                            "billing/models.py": "class Invoice(Model): pass\n"})
    found = sf.find_schema(repo)
    assert found["kind"] == "models"
    assert "class User" in found["text"] and "class Invoice" in found["text"]
    assert found["path"] == "2 models.py files"


def test_find_schema_returns_nothing_for_a_repo_with_no_schema(tmp_path):
    found = sf.find_schema(_repo(tmp_path, {"README.md": "# hi\n"}))
    assert found == {"kind": None, "path": None, "text": ""}


def test_find_schema_honours_an_explicit_override(tmp_path):
    """--schema points at a file the conventions would never find, and wins
    over a schema the walk would otherwise pick."""
    repo = _repo(tmp_path, {"db/schema.rb": "create_table :decoys\n",
                            "odd/place/tables.txt": "CREATE TABLE users();\n"})
    found = sf.find_schema(repo, override="odd/place/tables.txt")
    assert found["kind"] == "override"
    assert "CREATE TABLE users" in found["text"]
    assert "decoys" not in found["text"]


def test_find_migrations_returns_the_names_oldest_first(tmp_path):
    repo = _repo(tmp_path, {
        "db/migrate/20210101120000_create_users.rb": "x\n",
        "db/migrate/20220202120000_add_email.rb": "x\n",
    })
    reldir, names = sf.find_migrations(repo)
    assert reldir == "db/migrate"
    assert names == ["20210101120000_create_users", "20220202120000_add_email"]


@pytest.mark.parametrize("name,expected", [
    ("0001_initial.py", "0001_initial"),                    # Django: four digits
    ("20210605225044_init", "20210605225044_init"),          # Prisma: fourteen
    ("20210101120000_create_users.rb", "20210101120000_create_users"),  # Rails
])
def test_find_migrations_reads_every_framework_numbering(tmp_path, name, expected):
    """Was coderay-q2r.21: the pattern demanded six leading digits.

    Prisma and Rails both use fourteen, so only Django's four-digit numbering
    was dropped -- and dropped silently, as 'history squashed'. Django is the
    distinguishing input; the other two passed before the fix and must still.
    """
    repo = _repo(tmp_path, {f"app/migrations/{name}": "x\n"})
    _reldir, names = sf.find_migrations(repo)
    assert names == [expected]


def test_find_migrations_ignores_files_with_no_timestamp(tmp_path):
    repo = _repo(tmp_path, {
        "app/migrations/0001_initial.py": "x\n",
        "app/migrations/__init__.py": "x\n",
        "app/migrations/helpers.py": "x\n",
    })
    _reldir, names = sf.find_migrations(repo)
    assert names == ["0001_initial"]


def test_find_migrations_picks_the_directory_with_the_most_entries(tmp_path):
    """A repo can hold several migration directories; the real history is the
    biggest.

    find_migrations compares counts, so what this pins is that it compares at
    all: the decoy holds one entry and the real history three. Traversal order
    is not the discriminator -- os.walk gives no ordering guarantee, so a test
    resting on it would be pinning the filesystem, not the code.
    """
    repo = _repo(tmp_path, {
        "aaa/migrations/0001_initial.py": "x\n",
        "zzz/migrations/0001_initial.py": "x\n",
        "zzz/migrations/0002_more.py": "x\n",
        "zzz/migrations/0003_yet_more.py": "x\n",
    })
    reldir, names = sf.find_migrations(repo)
    assert reldir == "zzz/migrations"
    assert len(names) == 3


def test_find_migrations_returns_nothing_when_there_is_no_history(tmp_path):
    assert sf.find_migrations(_repo(tmp_path, {"README.md": "# hi\n"})) == (None, [])


def test_find_schema_refuses_a_schema_symlinked_out_of_the_repo(tmp_path):
    """coderay-q2r.28. The schema is embedded in every deep-dive batch."""
    import os
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE-SECRET-CONTENT\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"README.md": "# hi\n"})
    os.makedirs(os.path.join(repo, "db"), exist_ok=True)
    os.symlink(outside, os.path.join(repo, "db", "schema.rb"))

    assert "OUTSIDE-SECRET-CONTENT" not in sf.find_schema(repo)["text"]


def test_find_schema_caps_a_single_oversized_schema_and_says_so(tmp_path):
    """coderay-q2r.29. The schema goes into the tour prompt, the flows prompt
    and every deep-dive batch, so its size is multiplied by the run."""
    repo = _repo(tmp_path, {"schema.sql": "x" * (sf.SCHEMA_BUDGET + 50_000)})
    found = sf.find_schema(repo)
    assert len(found["text"]) < sf.SCHEMA_BUDGET + 1_000
    assert "TRUNCATED" in found["text"]


def test_find_schema_keeps_whole_model_files_and_drops_the_tail(tmp_path):
    """The budget caps HOW MANY files are included, never shortening each one.

    Inverting that was the root cause of two prior scalability bugs, so this
    asserts the kept files arrive complete.
    """
    each = sf.SCHEMA_BUDGET // 3
    repo = _repo(tmp_path, {f"app{i}/models.py": f"# marker{i}\n" + "m" * each
                            for i in range(5)})
    found = sf.find_schema(repo)
    assert found["kind"] == "models"
    assert "of 5 found" in found["path"]
    assert "# ===== TRUNCATED" not in found["text"]   # whole files, fewer of them
