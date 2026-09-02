import os

from crack.core import env_defaults

def test_sets_absent_key_and_restores_it():
    assert "CRACK_TEST_ABSENT" not in os.environ
    with env_defaults({"CRACK_TEST_ABSENT": "32768"}):
        assert os.environ["CRACK_TEST_ABSENT"] == "32768"
    assert "CRACK_TEST_ABSENT" not in os.environ

def test_a_value_the_user_already_set_wins(monkeypatch):
    monkeypatch.setenv("CRACK_TEST_PRESENT", "mine")
    with env_defaults({"CRACK_TEST_PRESENT": "theirs"}):
        assert os.environ["CRACK_TEST_PRESENT"] == "mine"
    assert os.environ["CRACK_TEST_PRESENT"] == "mine"

def test_restores_on_exception():
    try:
        with env_defaults({"CRACK_TEST_RAISES": "1"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "CRACK_TEST_RAISES" not in os.environ

def test_empty_defaults_is_a_no_op():
    before = dict(os.environ)
    with env_defaults({}):
        assert dict(os.environ) == before
    assert dict(os.environ) == before
