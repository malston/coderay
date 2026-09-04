import os

from crawl.core import env_defaults

def test_sets_absent_key_and_restores_it():
    assert "CRAWL_TEST_ABSENT" not in os.environ
    with env_defaults({"CRAWL_TEST_ABSENT": "32768"}):
        assert os.environ["CRAWL_TEST_ABSENT"] == "32768"
    assert "CRAWL_TEST_ABSENT" not in os.environ

def test_a_value_the_user_already_set_wins(monkeypatch):
    monkeypatch.setenv("CRAWL_TEST_PRESENT", "mine")
    with env_defaults({"CRAWL_TEST_PRESENT": "theirs"}):
        assert os.environ["CRAWL_TEST_PRESENT"] == "mine"
    assert os.environ["CRAWL_TEST_PRESENT"] == "mine"

def test_restores_on_exception():
    try:
        with env_defaults({"CRAWL_TEST_RAISES": "1"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "CRAWL_TEST_RAISES" not in os.environ

def test_empty_defaults_is_a_no_op():
    before = dict(os.environ)
    with env_defaults({}):
        assert dict(os.environ) == before
    assert dict(os.environ) == before
