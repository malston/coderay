import pytest

import crawl.core.llm as llm_module
from crawl.analyses.interfaces import nodes as n

CARDS = "### Booking (12)\nbody\n\n### Auth (3)\nbody\n"


def _fake_llm(monkeypatch, fn):
    """Fake the LLM at both boundaries the node calls through.

    EndpointSequence reaches the model two ways: directly via call_llm for the
    diagram, and via crawl.core.yaml_call for the endpoint pick. yaml_call
    resolves call_llm in its own module, so patching only this module's name
    would leave the pick calling the real API.
    """
    monkeypatch.setattr(n, "call_llm", fn)
    monkeypatch.setattr(llm_module, "call_llm", fn)


def _sequence_node():
    node = n.EndpointSequence()
    node.wait = 0
    return node


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

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m",
              "flows_md": "### F\nbody\n", "route_files": ["pages/api/book.ts"]}
    _sequence_node().run(shared)
    assert shared["sequence_endpoint"] == "POST /api/book"
    assert shared["sequence_files"] == ["pages/api/book.ts"]
    # The handler source reached the diagram prompt, which is the point of step 1.
    assert "export default function book" in prompts[1]


def test_endpoint_sequence_falls_back_to_the_largest_handler_when_the_pick_is_unusable(
        tmp_path, monkeypatch, capsys):
    """The pick giving up must not cost the section, and must not be silent.

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

    def reply(prompt):
        if "sequence diagram" in prompt:      # the pick, never usable here
            return "not yaml at all"
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/aaa.ts", "pages/api/zzz.ts"]}
    _sequence_node().run(shared)
    assert shared["sequence_files"] == ["pages/api/zzz.ts"]
    assert shared["sequence_endpoint"] == "pages/api/zzz.ts"
    assert "falling back" in capsys.readouterr().out


def test_endpoint_sequence_retries_a_reply_with_no_diagram(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n"})
    pick = '```yaml\nendpoint: "POST /x"\nfiles:\n  - pages/api/book.ts\n```'
    calls = []

    def reply(p):
        calls.append(p)
        return pick if "sequence diagram" in p else (
            "no diagram" if len(calls) < 5 else "```mermaid\nsequenceDiagram\n  a->>b: hi\n```")

    _fake_llm(monkeypatch, reply)
    node = _sequence_node()
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


def test_the_endpoint_pick_retries_a_malformed_reply_instead_of_giving_up(tmp_path, monkeypatch):
    """The pick goes through crawl.core.yaml_call, which retries a bad reply
    with a varied tail rather than accepting the first failure.

    The distinguishing input is a first reply that is not YAML followed by a
    good one: swallowing the parse error would take the fallback and lose the
    endpoint the model went on to name correctly.
    """
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n",
                            "pages/api/other.ts": "x\n" * 50})
    replies = [
        "sorry, here is prose instead of yaml",
        '```yaml\nendpoint: "POST /api/book"\nfiles:\n  - pages/api/book.ts\n```',
        "```mermaid\nsequenceDiagram\n  a->>b: hi\n```",
    ]
    _fake_llm(monkeypatch, lambda p: replies.pop(0))
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/book.ts", "pages/api/other.ts"]}
    _sequence_node().run(shared)
    assert shared["sequence_endpoint"] == "POST /api/book"
    assert shared["sequence_files"] == ["pages/api/book.ts"]


def test_a_network_error_during_the_pick_is_not_turned_into_a_silent_fallback(
        tmp_path, monkeypatch):
    """A blanket `except Exception` around the pick swallowed transport errors
    too, quietly degrading the diagram instead of letting the node retry.

    yaml_call catches only parse and validation failures, so this propagates.
    """
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n"})

    def reply(prompt):
        # Only the pick call fails. The diagram call succeeds, so a swallowed
        # transport error would look like a clean run that merely fell back --
        # which is exactly the failure this test exists to catch.
        if "sequence diagram" in prompt:
            raise RuntimeError("connection reset")
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    node = _sequence_node()
    with pytest.raises(RuntimeError, match="connection reset"):
        node.run({"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
                  "route_files": ["pages/api/book.ts"]})


def test_the_endpoint_pick_retries_well_formed_yaml_that_names_nothing(tmp_path, monkeypatch):
    """A reply can parse cleanly and still be useless.

    `endpoint: ""` with no files is valid YAML, so a parse-only check accepts
    it, read_files gets an empty list, and the run drops to the fallback
    without ever asking the model again. The pick is validated, not just
    parsed, so yaml_call retries and the second reply is used. The fallback
    would have chosen zzz.ts, so taking book.ts is what proves the retry.
    """
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n",
                            "pages/api/zzz.ts": "much longer handler\n" * 20})
    replies = [
        '```yaml\nendpoint: ""\nfiles: []\n```',
        '```yaml\nendpoint: "POST /api/book"\nfiles:\n  - pages/api/book.ts\n```',
        "```mermaid\nsequenceDiagram\n  a->>b: hi\n```",
    ]
    _fake_llm(monkeypatch, lambda p: replies.pop(0))
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/book.ts", "pages/api/zzz.ts"]}
    _sequence_node().run(shared)
    assert shared["sequence_endpoint"] == "POST /api/book"
    assert shared["sequence_files"] == ["pages/api/book.ts"]


def test_the_module_does_not_carry_its_own_yaml_parser():
    """CLAUDE.md: LLM YAML parsing goes through crawl.core, not a local copy.

    The duplicate was a real cache/retry defect once before.
    """
    assert not hasattr(n, "parse_yaml")


@pytest.mark.parametrize("body,shape", [
    ("- a\n- b", "list"),
    ("just a bare string", "scalar"),
    ("42", "number"),
])
def test_a_pick_that_is_not_a_mapping_retries_and_then_falls_back(
        tmp_path, monkeypatch, body, shape):
    """Well-formed YAML of the wrong shape must not kill the run.

    `data or {}` guards None but not shape: a list is truthy, so .get() raised
    AttributeError, which yaml_call does not catch and exec's `except
    AssertionError` did not either. PocketFlow then re-raised it and the whole
    interfaces run died on a bad endpoint pick that the fallback exists to
    absorb. The diagram call below succeeds, so a surviving crash can only come
    from the pick.
    """
    repo = _repo(tmp_path, {"pages/api/book.ts": "export default book\n"})

    def reply(prompt):
        if "sequence diagram" in prompt:
            return f"```yaml\n{body}\n```"
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/book.ts"]}
    _sequence_node().run(shared)
    assert "sequenceDiagram" in shared["sequence_md"]
    assert shared["sequence_files"] == ["pages/api/book.ts"]


def test_a_scalar_files_reply_is_rejected_rather_than_iterated_per_character(
        tmp_path, monkeypatch):
    """`files: path/to/one.ts` is a plausible reply, and iterating a string
    yields its characters.

    Those one-character paths reach read_files' matcher, which resolves each
    against the repo index -- "s" matches a file at path `s` -- so the diagram
    gets drawn from files unrelated to the endpoint, with a card header naming
    the endpoint and a stdout line reporting a plausible file count. The file
    `s` below is what a per-character read would pull in; the fallback picks
    the largest pages/api handler instead.
    """
    repo = _repo(tmp_path, {"pages/api/aaa.ts": "small\n",
                            "pages/api/zzz.ts": "much longer handler\n" * 20,
                            "s": "unrelated\n"})

    def reply(prompt):
        if "sequence diagram" in prompt:
            return '```yaml\nendpoint: "POST /x"\nfiles: src/pages/api/checkout.ts\n```'
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/aaa.ts", "pages/api/zzz.ts"]}
    _sequence_node().run(shared)
    assert shared["sequence_files"] == ["pages/api/zzz.ts"]
    assert "s" not in shared["sequence_files"]


def test_a_valid_pick_whose_files_all_miss_says_so_before_falling_back(
        tmp_path, monkeypatch, capsys):
    """The pick names an endpoint and files that resolve to nothing in the repo.
    The fallback draws the diagram from the largest route file, so the terminal
    must say which model-named files were dropped; otherwise a card titled with
    the model's endpoint is drawn from an unrelated file with no marker."""
    repo = _repo(tmp_path, {"pages/api/aaa.ts": "small\n",
                            "pages/api/zzz.ts": "much longer handler\n" * 20})

    def reply(prompt):
        if "sequence diagram" in prompt:
            return '```yaml\nendpoint: "POST /api/book"\nfiles:\n  - nope/none.py\n  - gone.ts\n```'
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["pages/api/aaa.ts", "pages/api/zzz.ts"]}
    _sequence_node().run(shared)
    out = capsys.readouterr().out
    assert shared["sequence_files"] == ["pages/api/zzz.ts"]
    assert "nope/none.py" in out and "gone.ts" in out and "falling back" in out


def test_the_sequence_fallback_uses_a_non_nextjs_route_file(tmp_path, monkeypatch):
    """coderay-q2r.25. Rails, Django, Go, tRPC and GraphQL had no candidates.

    This repo has no pages/api at all, so the old filter returned nothing and
    the diagram was drawn from the route list with no source. Both files are
    route files; the larger one must win.
    """
    repo = _repo(tmp_path, {"config/routes.rb": "Rails.routes\n",
                            "app/urls.py": "urlpatterns = []\n" * 40})

    def reply(prompt):
        if "sequence diagram" in prompt:
            return "not yaml at all"
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": ["config/routes.rb", "app/urls.py"]}
    _sequence_node().run(shared)
    assert shared["sequence_files"] == ["app/urls.py"]
    assert shared["sequence_grounded"] is True


def test_a_diagram_drawn_with_no_handler_source_is_marked_ungrounded(tmp_path, monkeypatch):
    """With no route file readable at all there is nothing to ground it in, and
    that fact has to reach the page rather than only stdout."""
    repo = _repo(tmp_path, {"config/routes.rb": "Rails.routes\n"})

    def reply(prompt):
        if "sequence diagram" in prompt:
            return "not yaml at all"
        return "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "routes": "r", "menu_md": "m", "flows_md": "",
              "route_files": []}          # nothing to fall back to
    _sequence_node().run(shared)
    assert shared["sequence_grounded"] is False
