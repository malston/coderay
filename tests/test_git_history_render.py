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


def test_pct_label_formats_a_plain_number():
    assert r._pct_label(45) == "45"
    assert r._pct_label("45") == "45"


def test_pct_label_strips_a_percent_sign_the_model_appended():
    assert r._pct_label("45%") == "45"


def test_pct_label_returns_a_question_mark_for_missing_or_unparseable_input():
    assert r._pct_label(None) == "?"
    assert r._pct_label("not a number") == "?"


def test_pct_label_clamps_to_0_100_like_pct_does():
    """coderay-6ts.2. _pct clamps an out-of-range model value to [0, 100];
    _pct_label (the markdown cast/mood twin) did not, so the same input
    rendered differently between the HTML bars and the markdown lines."""
    assert r._pct_label(150) == "100"
    assert r._pct_label(-5) == "0"


def test_pct_falls_back_to_zero_on_nan():
    """coderay-ziw.3. `min(100, float('nan'))` returns 100 because NaN never
    wins a comparison, so a model value that parses to NaN slipped past the
    clamp and rendered as a full bar instead of falling back like other
    unparseable input."""
    assert r._pct(float("nan")) == 0
    assert r._pct("nan") == 0


def test_pct_label_falls_back_to_question_mark_on_nan():
    """coderay-ziw.3. Same NaN-clamp bug as _pct, reached through the
    markdown cast/mood twin."""
    assert r._pct_label(float("nan")) == "?"
    assert r._pct_label("nan") == "?"


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
