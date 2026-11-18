from __future__ import annotations

from ia_orchestrator import keep_awake


class _Proc:
    def __init__(self, code: int | None = None) -> None:
        self._code = code
        self.stopped = False

    def poll(self) -> int | None:
        return self._code

    def terminate(self) -> None:
        self.stopped = True
        self._code = 0

    def kill(self) -> None:
        self.stopped = True
        self._code = 0

    def wait(self, timeout: float = 5) -> int:
        return 0


def test_caffeinate_argv_keeps_user_active_for_parent_lifetime():
    argv = keep_awake.caffeinate_argv(4242)
    assert argv[:4] == ["caffeinate", "-d", "-i", "-u"]
    assert argv[4:6] == ["/bin/sh", "-c"]
    assert 'kill -0 "$1"' in argv[6]
    assert argv[-2:] == ["ia-orchestrator-monitor", "4242"]


def test_main_skips_outside_macos(monkeypatch):
    monkeypatch.setattr(keep_awake.sys, "platform", "linux")
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("não deve lançar caffeinate")

    monkeypatch.setattr(keep_awake.subprocess, "Popen", boom)
    assert keep_awake.main() == 0
    assert called["n"] == 0


def test_supervise_stops_when_parent_exits():
    proc = _Proc()
    pids = iter([10, 1])

    def getppid() -> int:
        return next(pids)

    code = keep_awake.supervise(proc, 10, sleep=lambda _s: None, getppid=getppid, interval=0)
    assert code == 0
    assert proc.stopped is True


def test_supervise_returns_caffeinate_exit():
    proc = _Proc(code=0)
    code = keep_awake.supervise(proc, 10, sleep=lambda _s: None, getppid=lambda: 10, interval=0)
    assert code == 0
    assert proc.stopped is False


def test_spawn_uses_module(monkeypatch):
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return object()

    monkeypatch.setattr(keep_awake.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(keep_awake.sys, "executable", "/usr/bin/python3")
    keep_awake.spawn()
    assert captured["argv"] == ["/usr/bin/python3", "-m", "ia_orchestrator.keep_awake"]


def test_main_on_macos_passes_parent_pid_to_caffeinate(monkeypatch):
    captured: dict = {}

    class Proc:
        def poll(self):
            return 0

    def fake_popen(argv, **_kwargs):
        captured["argv"] = argv
        return Proc()

    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.os, "getppid", lambda: 777)
    monkeypatch.setattr(keep_awake.subprocess, "Popen", fake_popen)

    assert keep_awake.main() == 0
    assert captured["argv"] == keep_awake.caffeinate_argv(777)
    assert captured["argv"][-1] == "777"
