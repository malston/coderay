from crawl.analyses.git_history import render as r


def test_pct_reads_a_plain_number():
    assert r._pct(45) == 45
    assert r._pct("45") == 45


def test_pct_strips_a_percent_sign_the_model_appended():
    """coderay-q2r.43. `float('45%')` raises ValueError and _pct swallowed it
    into 0, flattening every bar a model wrote with a trailing '%' on."""
    assert r._pct("45%") == 45
    assert r._pct(" 45 % ") == 45


def test_pct_clamps_and_falls_back_to_zero_on_real_garbage():
    assert r._pct(150) == 100
    assert r._pct(-5) == 0
    assert r._pct("not a number") == 0
    assert r._pct(None) == 0


def test_bars_renders_a_percent_sign_only_once():
    html = r._bars([{"name": "Refactors", "pct": "45%"}])
    assert "45%" in html
    assert "45%%" not in html


def test_grave_placeholder_says_no_deletions_when_there_truly_were_none():
    html = r.render_html("repo", {"bulk_dels": [], "graves": []})
    assert "No bulk deletions found." in html


def test_render_markdown_cast_percent_does_not_double_up_a_percent_sign():
    """coderay-q2r.43. Same _pct bug, reached through the markdown cast/mood
    lines rather than the HTML bars: `f"{p.get('pct','?')}%"` on a model value
    of "45%" printed "45%%"."""
    shared = {"commits": [], "eras": [{"name": "Era", "start": "2020-01", "end": "2020-12",
                                       "description": "d"}],
              "profiles": [{"era": {"name": "Era"},
                            "profile": {"cast": {"contributors": [{"name": "A", "pct": "45%"}]},
                                        "mood": {"patterns": [{"label": "Refactors", "pct": "45%"}]}}}],
              "graves": []}
    md = r.render_markdown("repo", shared)
    assert "45%%" not in md
    assert "(45%)" in md


def test_grave_placeholder_says_deletions_were_filtered_when_bulk_dels_is_non_empty():
    """coderay-q2r.43. `bulk_dels` had candidates but every one was dropped by
    grave_min_files or the noise filter; 'No bulk deletions found' is false in
    that case even though the console line ('Wrote 0 graveyard entries') is
    accurate about what actually got written."""
    shared = {"bulk_dels": [{"hash": "a" * 40, "count": 9, "scope": "vendor"}], "graves": []}
    html = r.render_html("repo", shared)
    assert "No bulk deletions found." not in html
    assert "1 bulk deletion" in html
