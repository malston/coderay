import pytest

from crawl.analyses.schema import schema_find as sf


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
    assert found == {"kind": None, "path": None, "files": [], "text": ""}


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
    ("00001_init.sql", "00001_init"),                                    # goose
    ("000001_init.up.sql", "000001_init"),                               # golang-migrate
])
def test_find_migrations_reads_every_framework_numbering(tmp_path, name, expected):
    """TIMESTAMP_RE accepts four or more leading digits, so Django (four), goose
    (five), golang-migrate (six) and Prisma or Rails (fourteen) all pass; a
    six-digit minimum drops every Django history silently, as "squashed"
    (coderay-q2r.21)."""
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
    # coderay-3eu: the manifest lists the kept files, not the five found
    import re
    assert 0 < len(found["files"]) < 5
    assert found["files"] == re.findall(r"^# ===== (\S+) =====$", found["text"], re.M)


def test_find_schema_refuses_a_schema_symlinked_to_an_in_repo_credential_file(tmp_path):
    """coderay-q2r.56. `db/schema.rb -> ../.env` resolves inside the repo, so
    containment alone let the .env body into every deep-dive batch."""
    import os
    repo = _repo(tmp_path / "repo", {"README.md": "# hi\n", ".env": "TOKEN=hunter2\n"})
    os.makedirs(os.path.join(repo, "db"), exist_ok=True)
    os.symlink(os.path.join(repo, ".env"), os.path.join(repo, "db", "schema.rb"))

    assert "hunter2" not in sf.find_schema(repo)["text"]


def test_find_schema_skips_a_virtualenv_named_env(tmp_path):
    """PR #30 review. Django's own models.py and auth migrations under env/
    outranked the app's; SKIP_DIRS is the shared DEFAULT_SKIP_DIR."""
    repo = _repo(tmp_path, {
        "app/models.py": "class User: pass\n",
        "env/lib/python3.12/site-packages/django/contrib/auth/models.py": "ignored\n",
        "app/migrations/0001_initial.py": "",
        **{f"env/lib/python3.12/site-packages/django/contrib/auth/migrations/{i:04d}_x.py": ""
           for i in range(1, 13)},
    })
    assert "ignored" not in sf.find_schema(repo)["text"]
    assert sf.find_migrations(repo)[0] == "app/migrations"


# coderay-5wu.13. A Go service often keeps its schema as CREATE TABLE statements
# inside Go string literals, migrating in code; there is no schema file to find.
GO_DB = '''package hub

import "database/sql"

func migrate(db *sql.DB) error {
	if db == nil {
		return fmt.Errorf("open db: %w", errNil)
	}
	_, _ = db.Exec(`ALTER TABLE claws ADD COLUMN provider TEXT NOT NULL DEFAULT ''`)
	_, _ = db.Exec("create table sessions (id TEXT PRIMARY KEY)")
	_, _ = db.Exec(`CREATE UNIQUE INDEX idx_claws_tenant ON claws(tenant_id)`)
	_, err := db.Exec(`
	CREATE TABLE IF NOT EXISTS tenants (
		id TEXT PRIMARY KEY
	);

	CREATE TABLE IF NOT EXISTS claws (
		id TEXT PRIMARY KEY,
		tenant_id TEXT NOT NULL REFERENCES tenants(id)
	);
	`)
	return err
}
'''


def test_find_schema_reads_create_table_statements_embedded_in_go(tmp_path):
    repo = _repo(tmp_path, {"pkg/hub/db.go": GO_DB, "pkg/hub/server.go": "package hub\n"})
    found = sf.find_schema(repo)
    assert found["kind"] == "embedded-sql"
    assert "pkg/hub/db.go" in found["path"]
    assert "CREATE TABLE IF NOT EXISTS claws" in found["text"]
    assert "ALTER TABLE claws ADD COLUMN provider" in found["text"]
    assert "create table sessions" in found["text"]            # interpreted string, lowercase
    assert "CREATE UNIQUE INDEX idx_claws_tenant" in found["text"]
    assert "func migrate" not in found["text"] and "db.Exec" not in found["text"]
    assert "database/sql" not in found["text"] and "open db" not in found["text"]


def test_embedded_sql_files_are_ordered_by_how_many_tables_they_create(tmp_path):
    """The file with most of the schema leads; a file that creates one table
    for a feature follows; a .go file with no SQL, a test file and a fixture
    directory are not part of the schema."""
    one = 'package a\n_ = `CREATE TABLE IF NOT EXISTS analytics (id TEXT)`\n'
    repo = _repo(tmp_path, {
        "pkg/hub/analytics_api.go": one,
        "pkg/hub/db.go": GO_DB,
        "pkg/hub/db_test.go": GO_DB,
        "pkg/hub/factorytest/fixture.go": GO_DB,
        "pkg/hub/server.go": "package hub\n",
    })
    found = sf.find_schema(repo)
    assert found["path"] == "2 Go files with embedded SQL (pkg/hub/db.go, pkg/hub/analytics_api.go)"
    assert found["text"].index("db.go") < found["text"].index("analytics_api.go")
    assert "fixture" not in found["text"] and "db_test" not in found["text"]


def test_find_schema_prefers_a_schema_file_over_embedded_sql(tmp_path):
    repo = _repo(tmp_path, {"schema.sql": "CREATE TABLE x (id int);\n", "pkg/hub/db.go": GO_DB})
    assert sf.find_schema(repo)["kind"] == "sql"


def test_find_schema_prefers_model_files_over_embedded_sql(tmp_path):
    """A models.py is a schema by convention; DDL inside Go strings is a
    heuristic. A Django repo with a Go sidecar keeps its models."""
    repo = _repo(tmp_path, {"app/models.py": "class A: pass\n", "pkg/hub/db.go": GO_DB})
    assert sf.find_schema(repo)["kind"] == "models"


def test_embedded_sql_keeps_only_literals_that_are_statements(tmp_path):
    """An error message that mentions creating a table is prose, not schema;
    a literal counts when it begins with a DDL statement."""
    prose = 'package a\n_ = fmt.Errorf("failed to create table %s: %w", name, err)\nlog.Printf("create table %q failed", n)\n'
    repo = _repo(tmp_path, {"pkg/hub/errors.go": prose})
    assert sf.find_schema(repo)["kind"] is None
    assert sf.embedded_sql(prose) == ""


def test_embedded_sql_ignores_comments_and_rune_literals(tmp_path):
    """A backtick in a comment or a rune literal must not pair with a raw
    string's opening backtick; the scanner walks comments and runes as Go does."""
    text = ("package a\n// the ` rune starts a raw string\nr := '`'\nq := '\"'\n"
            "func migrate(db *sql.DB) {\n\tdb.Exec(`CREATE TABLE t (id int)`)\n}\n"
            "/* db.Exec(`CREATE TABLE old (id int)`) */\n")
    ddl = sf.embedded_sql(text)
    assert ddl == "CREATE TABLE t (id int)"


def test_embedded_sql_unescapes_interpreted_strings_and_keeps_inner_quotes(tmp_path):
    text = 'a := "CREATE TABLE \\"users\\" (id int)"\nb := `ALTER TABLE t RENAME TO "new_t"`\n'
    ddl = sf.embedded_sql(text)
    assert 'CREATE TABLE "users" (id int)' in ddl and 'RENAME TO "new_t"' in ddl
    from crawl.analyses.schema.nodes import schema_table_names
    assert schema_table_names(ddl) == {"users"}


def test_a_file_with_only_alter_table_statements_joins_the_schema(tmp_path):
    """Migrating in code often splits the CREATEs and the ALTERs across files;
    the columns added later belong to the schema."""
    repo = _repo(tmp_path, {
        "pkg/hub/schema.go": GO_DB,
        "pkg/hub/migrations.go": "package hub\n_ = `ALTER TABLE claws ADD COLUMN nix INTEGER NOT NULL DEFAULT 0`\n",
    })
    found = sf.find_schema(repo)
    assert "ADD COLUMN nix" in found["text"]
    assert found["text"].index("schema.go") < found["text"].index("migrations.go")


def test_go_files_are_not_read_when_a_schema_file_wins(tmp_path, monkeypatch):
    """The Go scan reads every candidate file whole; a repo that has a schema
    file must not pay for it, and a generated .go file over the per-file cap is
    never read at all."""
    from crawl.core import DEFAULT_MAX_FILE_BYTES
    repo = _repo(tmp_path, {"schema.prisma": "model User {}\n", "pkg/gen/big.go": "x" * (DEFAULT_MAX_FILE_BYTES + 1)})
    opened = []
    real = sf._read
    monkeypatch.setattr(sf, "_read", lambda path, *a, **k: opened.append(path) or real(path, *a, **k))
    assert sf.find_schema(repo)["kind"] == "prisma"
    assert not any(p.endswith(".go") for p in opened)
    repo2 = _repo(tmp_path / "two", {"pkg/gen/big.go": "x" * (DEFAULT_MAX_FILE_BYTES + 1), "pkg/hub/db.go": GO_DB})
    opened.clear()
    assert sf.find_schema(repo2)["kind"] == "embedded-sql"
    assert not any(p.endswith("big.go") for p in opened)


def test_find_migrations_counts_a_golang_migrate_pair_once(tmp_path):
    repo = _repo(tmp_path, {"db/migrations/000001_init.up.sql": "x\n", "db/migrations/000001_init.down.sql": "x\n",
                            "db/migrations/000002_users.up.sql": "x\n", "db/migrations/000002_users.down.sql": "x\n"})
    _reldir, names = sf.find_migrations(repo)
    assert names == ["000001_init", "000002_users"]


def test_embedded_sql_is_refused_from_a_go_file_symlinked_out_of_the_repo(tmp_path):
    import os
    outside = tmp_path / "outside.go"
    outside.write_text(GO_DB.replace("tenants", "LEAKED_TABLE"), encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"README.md": "x\n"})
    os.makedirs(os.path.join(repo, "pkg"), exist_ok=True)
    os.symlink(outside, os.path.join(repo, "pkg", "db.go"))
    found = sf.find_schema(repo)
    assert found["kind"] is None and "LEAKED_TABLE" not in found["text"]


def test_embedded_sql_table_names_reach_the_filter(tmp_path):
    """SchemaTour filters the model's ER diagram against the tables actually
    declared; the extracted SQL must carry the CREATE TABLE lines whole."""
    from crawl.analyses.schema.nodes import schema_table_names
    repo = _repo(tmp_path, {"pkg/hub/db.go": GO_DB})
    assert schema_table_names(sf.find_schema(repo)["text"]) == {"tenants", "claws", "sessions"}


def test_embedded_sql_ties_break_alphabetically_and_only_go_files_are_candidates(tmp_path):
    one = 'package a\n_ = `CREATE TABLE IF NOT EXISTS t (id TEXT)`\n'
    repo = _repo(tmp_path, {"pkg/b.go": one, "pkg/a.go": one, "pkg/c.sql.txt": one, "pkg/d.go.bak": one})
    found = sf.find_schema(repo)
    assert found["path"] == "2 Go files with embedded SQL (pkg/a.go, pkg/b.go)"


def test_embedded_sql_keeps_whole_files_and_drops_the_tail_under_the_budget(tmp_path, monkeypatch):
    """Same rule as the model files: whole blocks, fewer of them, and the path
    says how many were found. The first block is kept even when it alone
    exceeds the budget, so a single large schema is never silently empty."""
    monkeypatch.setattr(sf, "SCHEMA_BUDGET", 600)
    ddl = "CREATE TABLE IF NOT EXISTS t%d (\n" + "  c TEXT,\n" * 20 + "  id TEXT\n)"
    files = {f"pkg/m{i}.go": "package a\n_ = `" + ddl % i + "`\n" for i in range(4)}
    found = sf.find_schema(_repo(tmp_path, files))
    assert found["path"].startswith("2 Go files with embedded SQL") and found["path"].endswith(" of 4 found")
    assert len(found["files"]) == 2 and all(f"===== {f} =====" in found["text"] for f in found["files"])
    monkeypatch.setattr(sf, "SCHEMA_BUDGET", 50)
    found = sf.find_schema(_repo(tmp_path / "one", {"pkg/m.go": files["pkg/m0.go"]}))
    assert "CREATE TABLE IF NOT EXISTS t0" in found["text"] and found["path"].startswith("1 Go file with")


def test_find_schema_lists_the_files_it_read(tmp_path):
    """coderay-3eu: the manifest needs paths, and the models and embedded-SQL
    branches describe themselves in `path` with a sentence, not a path."""
    assert sf.find_schema(_repo(tmp_path, {"db/schema.rb": "create_table :users\n"}))["files"] == ["db/schema.rb"]


def test_find_schema_lists_every_models_file_it_joined(tmp_path):
    repo = _repo(tmp_path, {"a/models.py": "class A: pass\n", "b/models.py": "class B: pass\n"})
    found = sf.find_schema(repo)
    assert found["kind"] == "models" and sorted(found["files"]) == ["a/models.py", "b/models.py"]


def test_find_schema_override_lists_the_override(tmp_path):
    repo = _repo(tmp_path, {"custom/ddl.sql": "CREATE TABLE t();\n"})
    assert sf.find_schema(repo, override="custom/ddl.sql")["files"] == ["custom/ddl.sql"]
