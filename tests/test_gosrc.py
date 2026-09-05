"""crawl.core.gosrc reads Go far enough to separate comments, runes and strings."""
from crawl.core import gosrc


def test_string_literals_resolve_escapes_and_skip_comments_and_runes():
    text = ('// a ` in a comment\n'
            "r := '`'\n"
            'q := \'"\'\n'
            'a := "CREATE TABLE \\"users\\" (id int)\\n"\n'
            '/* `not a string` */\n'
            'b := `raw "quoted" text`\n')
    assert gosrc.string_literals(text) == ['CREATE TABLE "users" (id int)\n', 'raw "quoted" text']


def test_without_comments_keeps_strings_whole_and_drops_every_comment():
    text = 'u := "https://acme.com" // trailing\n/* block\nmux.Handle("/gone", h) */\nmux.Handle("/", h)\n'
    out = gosrc.without_comments(text)
    assert "https://acme.com" in out and "/gone" not in out and "trailing" not in out
    assert 'mux.Handle("/", h)' in out


def test_an_unterminated_raw_string_ends_the_scan_without_error():
    assert gosrc.string_literals('a := "ok"\nb := `never closed') == ["ok"]
