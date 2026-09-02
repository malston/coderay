import pytest

from crack.analyses.interfaces import nodes as n

CARDS = "### Booking (12)\nbody\n\n### Auth (3)\nbody\n"


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_find_routes_populates_the_surface(tmp_path):
    repo = _repo(tmp_path, {"config/routes.rb": "Rails.routes.draw\n"})
    shared = {"repo_path": repo}
    n.FindRoutes().run(shared)
    assert "Rails.routes.draw" in shared["routes"]
    assert shared["route_files"] == ["config/routes.rb"]


def test_find_routes_refuses_a_repo_with_no_surface_files(tmp_path):
    repo = _repo(tmp_path, {"README.md": "# a library\n"})
    with pytest.raises(AssertionError, match="No route/surface files found"):
        n.FindRoutes().run({"repo_path": repo})


def test_split_menu_separates_the_opener_the_groups_and_the_tour():
    opener, groups, tour = n.split_menu(
        "This API is about booking.\n\n"
        "### Booking (12)\nbody\n\n"
        "## A short tour\n\n### Step 1\nbody\n")
    assert opener == "This API is about booking."
    assert groups.startswith("### Booking (12)")
    assert "Step 1" in tour
    assert "Step 1" not in groups


def test_split_menu_keeps_every_group_when_the_model_wrote_no_tour():
    """The tour heading is optional; without it nothing may be cut."""
    opener, groups, tour = n.split_menu("Opener.\n\n### Booking (12)\nbody\n\n### Auth (3)\nbody\n")
    assert opener == "Opener."
    assert tour == ""
    assert "### Booking (12)" in groups and "### Auth (3)" in groups


def test_split_menu_matches_the_tour_heading_at_any_case():
    _opener, _groups, tour = n.split_menu("### G (1)\nbody\n\n## THE GUIDED TOUR\n\n### Step\nx\n")
    assert "Step" in tour


def test_split_menu_does_not_treat_a_group_card_as_the_tour():
    """`##` is the tour heading; `###` is a group. A regex that matched `#+`
    would cut the first group card whose name mentions a tour."""
    _opener, groups, tour = n.split_menu("### Tour management (4)\nbody\n")
    assert "### Tour management (4)" in groups
    assert tour == ""


def test_first_card_returns_only_the_first_card():
    md = "### One\nbody one\n\n### Two\nbody two\n"
    out = n.first_card(md)
    assert "body one" in out
    assert "body two" not in out


def test_first_card_falls_back_to_a_prefix_when_there_are_no_cards():
    assert n.first_card("just prose, no cards") == "just prose, no cards"


def test_api_menu_stores_the_split_and_the_group_names(monkeypatch):
    reply = "Opener line.\n\n### Booking (12)\nbody\n\n### Auth (3)\nbody\n"
    monkeypatch.setattr(n, "call_llm", lambda p: reply)
    shared = {"routes": "x"}
    n.ApiMenu().run(shared)
    assert shared["opener"] == "Opener line."
    assert shared["group_names"] == ["Booking (12)", "Auth (3)"]
    assert shared["menu_md"] == reply.strip()


@pytest.mark.parametrize("node_cls,key", [(n.ApiMenu, "menu_md"), (n.TraceActions, "flows_md")])
def test_the_card_nodes_retry_a_reply_with_no_cards(monkeypatch, node_cls, key):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "prose, no cards" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = node_cls()
    node.wait = 0
    shared = {"routes": "x", "group_names": ["Booking (12)"]}
    node.run(shared)
    assert len(calls) == 3
    assert shared[key] == CARDS.strip()


def test_trace_actions_is_given_the_group_names(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    n.TraceActions().run({"routes": "ROUTE-BUNDLE", "group_names": ["Booking (12)"]})
    assert "Booking (12)" in prompts[0]
    assert "ROUTE-BUNDLE" in prompts[0]


def test_trace_actions_falls_back_to_the_groups_markdown_when_no_names_parsed(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    n.TraceActions().run({"routes": "x", "group_names": [], "groups_md": "### Fallback group\n"})
    assert "Fallback group" in prompts[0]


def test_endpoint_sequence_reads_the_files_the_model_picks(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default function book() {}\n"})
    replies = [
        '```yaml\nendpoint: "POST /api/book"\nfiles:\n  - pages/api/book.ts\n```',
        "```mermaid\nsequenceDiagram\n  client->>api: POST /api/book\n```",
    ]
    prompts = []

    def reply(p):
        prompts.append(p)
        return replies[len(prompts) - 1]

    monkeypatch.setattr(n, "call_llm", reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m",
              "flows_md": "### F\nbody\n", "route_files": ["pages/api/book.ts"]}
    n.EndpointSequence().run(shared)
    assert shared["sequence_endpoint"] == "POST /api/book"
    assert shared["sequence_files"] == ["pages/api/book.ts"]
    # The handler source reached the diagram prompt, which is the point of step 1.
    assert "export default function book" in prompts[1]


def test_endpoint_sequence_falls_back_to_the_largest_handler_when_the_pick_is_unusable(
        tmp_path, monkeypatch):
    """The pick step returning junk must not cost the whole section.

    Two distinguishing choices in one repo. The small handler sorts first
    alphabetically, so picking the largest is what separates the fallback from
    taking whatever comes first. And pages/api sits at the repository root,
    which is the layout Next.js generates and the one the candidate filter used
    to miss for want of a leading slash (coderay-q2r.17): nested under src/ the
    old filter passed and this test would prove nothing.
    """
    repo = _repo(tmp_path, {
        "pages/api/aaa.ts": "small\n",
        "pages/api/zzz.ts": "much longer handler body\n" * 20,
    })
    replies = ["not yaml at all",
               "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"]
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or replies[len(prompts) - 1])
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/aaa.ts", "pages/api/zzz.ts"]}
    n.EndpointSequence().run(shared)
    assert shared["sequence_files"] == ["pages/api/zzz.ts"]
    assert shared["sequence_endpoint"] == "pages/api/zzz.ts"


def test_endpoint_sequence_retries_a_reply_with_no_diagram(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n"})
    pick = '```yaml\nendpoint: "POST /x"\nfiles:\n  - pages/api/book.ts\n```'
    calls = []

    def reply(p):
        calls.append(p)
        return pick if "sequence diagram" in p else (
            "no diagram" if len(calls) < 5 else "```mermaid\nsequenceDiagram\n  a->>b: hi\n```")

    monkeypatch.setattr(n, "call_llm", reply)
    node = n.EndpointSequence()
    node.wait = 0
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/book.ts"]}
    node.run(shared)
    assert "sequenceDiagram" in shared["sequence_md"]


@pytest.mark.parametrize("name", ["api-menu.md", "endpoint-sequence.md", "trace-action.md"])
def test_every_prompt_loads(name):
    assert n.load_prompt(name).strip()


def test_the_routes_slot_is_filled_before_the_prompt_goes_out(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    n.ApiMenu().run({"routes": "ROUTE-BUNDLE"})
    assert "{routes}" not in prompts[0]
    assert "ROUTE-BUNDLE" in prompts[0]
