import pytest

from crack.core.runner import run_flow


def test_run_flow_dumps_state_and_reraises_on_failure():
    class FailingFlow:
        def run(self, shared):
            raise RuntimeError("boom")

    dumped = {}

    def dump_state(shared, out_dir):
        dumped["shared"], dumped["out_dir"] = shared, out_dir
        return "/tmp/run_state.json"

    with pytest.raises(RuntimeError):
        run_flow(FailingFlow(), {"x": 1}, "/tmp", dump_state)

    assert dumped == {"shared": {"x": 1}, "out_dir": "/tmp"}


def test_run_flow_does_not_call_dump_state_on_success():
    class OkFlow:
        def run(self, shared):
            pass

    calls = []
    run_flow(OkFlow(), {}, "/tmp", lambda *a: calls.append(a))
    assert calls == []
