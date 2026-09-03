import pytest

from crack.analyses.schema import nodes as n

CARDS = "### 1 · users\nbody\n\n### 2 · orders\nbody\n"
ERD = "```mermaid\nerDiagram\n  users ||--o{ orders : places\n```"


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_find_schema_populates_the_schema_and_the_migrations(tmp_path):
    repo = _repo(tmp_path, {"db/schema.rb": "create_table :users\n",
                            "db/migrate/20210101120000_create_users.rb": "x\n"})
    shared = {"repo_path": repo}
    n.FindSchema().run(shared)
    assert "create_table :users" in shared["schema"]
    assert shared["schema_kind"] == "rails"
    assert shared["migration_names"] == ["20210101120000_create_users"]


def test_find_schema_refuses_a_repo_with_no_schema(tmp_path):
    repo = _repo(tmp_path, {"README.md": "# a static site\n"})
    with pytest.raises(AssertionError, match="No schema file found"):
        n.FindSchema().run({"repo_path": repo})


@pytest.mark.parametrize("text,expected", [
    ("model User {}", {"user"}),                                    # Prisma
    ('CREATE TABLE "orders" ();', {"orders"}),                      # SQL
    ("class Invoice(models.Model): pass", {"invoice"}),             # Django
    ('create_table "users", force: :cascade do |t|\nend', {"users"}),  # Rails
])
def test_schema_table_names_reads_each_dialect(text, expected):
    """Rails was coderay-q2r.22.

    It is the distinguishing input: the SQL pattern needs CREATE\\s+TABLE, and
    schema.rb writes create_table with an underscore, so Rails came back empty
    while the other three passed. Empty `known` filters every entity out of the
    ER diagram, and the deep dive then reviews no tables at all.
    """
    assert n.schema_table_names(text) == expected


def test_an_empty_table_list_is_what_a_missing_dialect_costs():
    """Why q2r.22 mattered downstream, in one line: nothing survives the filter."""
    erd = "erDiagram\n  users ||--o{ bookings : places"
    assert n.tables_from_erd(erd, set()) == []


def test_tables_from_erd_keeps_only_entities_that_exist_in_the_schema():
    """The model invents entities. An ERD naming a table the schema does not
    declare must not reach the deep dive, which would then describe nothing.
    """
    erd = "erDiagram\n  users ||--o{ orders : places\n  users ||--o{ ghosts : haunts"
    assert n.tables_from_erd(erd, {"users", "orders"}) == ["users", "orders"]


def test_tables_from_erd_keeps_first_appearance_order_without_duplicates():
    erd = "erDiagram\n  orders }o--|| users : placed_by\n  orders ||--o{ items : has"
    assert n.tables_from_erd(erd, {"users", "orders", "items"}) == ["orders", "users", "items"]


def test_tables_from_headers_is_the_fallback_when_no_erd_parsed():
    md = "### Step 1 (`users`, `orders`)\nbody\n\n### Step 2 (`users`)\nbody\n"
    assert n.tables_from_headers(md) == ["users", "orders"]


def test_schema_tour_stores_the_erd_the_product_and_the_tables(monkeypatch):
    reply = ("**Product:** Acme Booking\n"
             "**Schema one-liner:** Bookings against rooms.\n\n"
             + ERD + "\n\n" + CARDS)
    monkeypatch.setattr(n, "call_llm", lambda p: reply)
    shared = {"schema": "model users {}\nmodel orders {}", "repo_path": "/tmp/toy_repo"}
    n.SchemaTour().run(shared)
    assert shared["product_name"] == "Acme Booking"
    assert shared["one_liner"] == "Bookings against rooms."
    assert shared["erd"].startswith("erDiagram")
    assert shared["table_list"] == ["users", "orders"]


def test_schema_tour_takes_the_er_diagram_not_whichever_fence_came_first(monkeypatch):
    """The hero renders an ERD. A reply that opens with a flowchart would
    otherwise put the wrong diagram there with nothing to signal it.
    """
    reply = ("**Product:** Acme\n\n"
             "```mermaid\nflowchart LR\n  a --> b\n```\n\n" + ERD + "\n\n" + CARDS)
    monkeypatch.setattr(n, "call_llm", lambda p: reply)
    shared = {"schema": "model users {}\nmodel orders {}", "repo_path": "/tmp/toy_repo"}
    n.SchemaTour().run(shared)
    assert shared["erd"].startswith("erDiagram")


def test_schema_tour_names_the_product_after_the_directory_for_a_relative_path(
        tmp_path, monkeypatch):
    """Was coderay-q2r.20: a naive basename yields "." for a relative repo path.

    product_name is not cosmetic: THEME.page_name prefers it over the name the
    renderer is given, so the page title became a dot, and it is interpolated
    into the deep-dive prompt as the product's name. "." is the input where
    basename and repo_name_of disagree.
    """
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(n, "call_llm", lambda p: ERD + "\n\n" + CARDS)  # no **Product:** line
    shared = {"schema": "model users {}", "repo_path": "."}
    n.SchemaTour().run(shared)
    assert shared["product_name"] == "toy_repo"


def test_trace_flows_is_given_the_table_list(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    n.TraceFlows().run({"schema": "SCHEMA-TEXT", "table_list": ["users", "orders"]})
    assert "`users`, `orders`" in prompts[0]
    assert "SCHEMA-TEXT" in prompts[0]


def test_table_deep_dive_batches_the_tables(monkeypatch):
    """One call per BATCH tables, not one call for all of them: a single call
    for twenty detailed cards overflows the output budget and truncates."""
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    shared = {"schema": "s", "product_name": "Acme", "one_liner": "x",
              "table_list": [f"t{i}" for i in range(9)]}
    n.TableDeepDive().run(shared)
    assert len(prompts) == 3          # 4 + 4 + 1
    assert "`t0`, `t1`, `t2`, `t3`" in prompts[0]
    assert "`t8`" in prompts[2]


def test_table_deep_dive_drops_each_batch_preamble_so_the_cards_concatenate(monkeypatch):
    """A model that opens with prose would otherwise wedge it between batches."""
    monkeypatch.setattr(n, "call_llm", lambda p: "Here are the tables:\n\n" + CARDS)
    shared = {"schema": "s", "product_name": "Acme", "one_liner": "x",
              "table_list": ["a", "b", "c", "d", "e"]}
    n.TableDeepDive().run(shared)
    assert shared["deepdive_md"].startswith("###")
    assert "Here are the tables" not in shared["deepdive_md"]


def test_migration_acts_skips_a_history_too_short_to_cluster(monkeypatch):
    """Fewer than four migrations is not a roadmap, and asking anyway invites
    the model to invent one. The LLM must not be called at all."""
    calls = []
    monkeypatch.setattr(n, "call_llm", lambda p: calls.append(p) or CARDS)
    shared = {"migration_names": ["0001_initial", "0002_more"]}
    n.MigrationActs().run(shared)
    assert calls == []
    assert shared["migration_md"] is None


def test_migration_acts_clusters_a_real_history(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    names = [f"0{i:03d}_change" for i in range(1, 7)]
    shared = {"migration_names": names}
    n.MigrationActs().run(shared)
    assert shared["migration_md"] == CARDS.strip()
    assert "0001_change" in prompts[0] and "0006_change" in prompts[0]


@pytest.mark.parametrize("node_cls,key,extra", [
    (n.SchemaTour, "tour_md", {"repo_path": "/tmp/toy_repo"}),
    (n.TraceFlows, "flows_md", {"table_list": ["users"]}),
])
def test_the_card_nodes_retry_a_reply_with_no_cards(monkeypatch, node_cls, key, extra):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "prose, no cards" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = node_cls()
    node.wait = 0
    shared = {"schema": "model users {}", **extra}
    node.run(shared)
    assert len(calls) == 3


@pytest.mark.parametrize("name", ["schema-tour.md", "trace-flows.md",
                                  "table-deep-dive.md", "migration-acts.md"])
def test_every_prompt_loads(name):
    assert n.load_prompt(name).strip()


def test_migration_acts_retries_a_reply_with_no_act_cards(monkeypatch):
    """coderay-q2r.23. This was the only LLM node in the three ports with no
    assertion on its output.

    Without it an empty reply flowed through to the renderer, which keys its
    skip note on the section being empty and so announced the deliberate
    too-few reason for a history that was not too few.
    """
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = n.MigrationActs()
    node.wait = 0
    shared = {"migration_names": [f"0{i:03d}_change" for i in range(1, 7)]}
    node.run(shared)
    assert len(calls) == 3
    assert shared["migration_md"] == CARDS.strip()


@pytest.mark.parametrize("text,expected", [
    ("CREATE TABLE IF NOT EXISTS users (id int);", {"users"}),
    ("CREATE TABLE public.orders (id int);", {"orders"}),
    ("CREATE TABLE `items` (id int);", {"items"}),
    ('CREATE TABLE "public"."evts" (id int);', {"evts"}),
    ("CREATE UNLOGGED TABLE jobs (id int);", {"jobs"}),
])
def test_schema_table_names_reads_the_ordinary_sql_spellings(text, expected):
    """coderay-q2r.26.

    Two of these were worse than a miss: IF NOT EXISTS put "if" in the set and
    public.orders put "public". `known` filters the ER diagram entities against
    this set, so a keyword in it drops every real table and the deep dive falls
    back to whatever the model happened to backtick.
    """
    assert n.schema_table_names(text) == expected
