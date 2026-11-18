from __future__ import annotations

from ia_orchestrator.alerts import format_alert, notify, phase_for_envelope_type, _failure_line
from ia_orchestrator.config import AlertsSection
from ia_orchestrator.errors import NetworkError
from ia_orchestrator.loop import STATUS_GIT_ERROR, tick
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import MessageType, build_envelope, render_message
from ia_orchestrator.workers import Engine

from helpers import make_cfg, open_task, pair


class BoomEngine:
    def sync(self) -> int:
        raise NetworkError("github indisponível")


def test_phase_map():
    assert phase_for_envelope_type("request") == "envelope_arrived"
    assert phase_for_envelope_type("result") == "result_delivered"
    assert phase_for_envelope_type("complete") == "task_completed"
    assert phase_for_envelope_type("ack") is None
    assert phase_for_envelope_type("progress") is None


def test_notify_disabled_when_alerts_off(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, "p-alert-off", "org/off")
    cfg.alerts.enabled = False
    called = []

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("não deve enviar")

    monkeypatch.setattr("ia_orchestrator.alerts._send_fn", lambda: (boom, object))
    assert notify(cfg, "envelope_arrived", task_id="t") is False
    assert called == []


def test_push_and_progress_defaults(tmp_path):
    cfg = make_cfg(tmp_path, "p-defaults", "org/defaults")
    assert cfg.policy.allow_push is True
    assert cfg.policy.allow_merge is False
    assert cfg.policy.allow_deploy is False
    assert AlertsSection().enabled is True
    assert "execution_started" in AlertsSection().events
    assert cfg.alerts.enabled is False
    assert cfg.progress.enabled is True
    assert cfg.progress.interval_minutes == 15


def test_notify_swallows_webhook_errors(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, "p-alert-on", "org/on")
    cfg.alerts.enabled = True

    def boom(text, **_k):
        raise RuntimeError("webhook down")

    class Dummy:
        def __init__(self, **_k):
            pass

    monkeypatch.setattr("ia_orchestrator.alerts._send_fn", lambda: (boom, Dummy))
    assert notify(cfg, "quarantine", reason="hash") is False


def test_notify_logs_sanitized_failure(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path, "p-alert-log", "org/log")
    cfg.alerts.enabled = True

    def boom(text, **_k):
        raise RuntimeError("down https://discord.com/api/webhooks/9/secret-token")

    class Dummy:
        def __init__(self, **_k):
            pass

    monkeypatch.setattr("ia_orchestrator.alerts._send_fn", lambda: (boom, Dummy))
    assert notify(cfg, "execution_started", task_id="T") is False
    err = capsys.readouterr().err
    assert "phase=execution_started" in err
    assert "error=RuntimeError" in err
    assert "[webhook]" in err
    assert "secret-token" not in err
    line = _failure_line("execution_started", RuntimeError("https://discord.com/api/webhooks/1/abc"))
    assert "webhooks/1/abc" not in line


def test_notify_sends_when_enabled(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, "p-alert-send", "org/send")
    cfg.alerts.enabled = True
    captured: list[str] = []

    def fake_send(text, **_k):
        captured.append(text)
        return [{}]

    class Dummy:
        def __init__(self, **_k):
            pass

    monkeypatch.setattr("ia_orchestrator.alerts._send_fn", lambda: (fake_send, Dummy))
    assert notify(cfg, "execution_started", task_id="T1") is True
    assert "phase=execution_started" in captured[0]
    captured.clear()
    cfg.alerts.events = [event for event in cfg.alerts.events if event != "execution_started"]
    assert notify(cfg, "execution_started", task_id="T1") is False
    assert captured == []
    cfg.alerts.events = list(AlertsSection().events)
    assert notify(cfg, "envelope_arrived", type="request", task_id="T1") is True
    assert "phase=envelope_arrived" in captured[0]
    assert "project=p-alert-send" in captured[0]
    text = format_alert("quarantine", cfg, {"reason": "payload_sha256"})
    assert "reason=payload_sha256" in text


def test_ingest_alerts_arrival_and_quarantine_once(tmp_path, monkeypatch):
    phases: list[str] = []

    def capture(cfg, phase, **_fields):
        phases.append(phase)
        return True

    monkeypatch.setattr("ia_orchestrator.workers.alert_notify", capture)
    cfg_o, cfg_e, orch_store, exec_store, orch_t, exec_t = pair(tmp_path, "p-al", "org/al", {})
    cfg_o.alerts.enabled = True
    human_t = orch_t
    task_id, issue, _env = open_task(human_t, cfg_o, "abrir")
    engine = Engine(
        cfg_o,
        orch_store,
        orch_t,
        "orchestrator",
        dry_run=True,
        home=tmp_path / "home",
    )
    engine.sync()
    engine.sync()
    assert phases.count("envelope_arrived") == 1

    bad = "<!-- ia-orchestrator:message:v1 -->\n```json\n{not json\n```\n<!-- /ia-orchestrator:message -->"
    orch_t.create_comment(issue.number, bad)
    engine.sync()
    engine.sync()
    assert phases.count("quarantine") == 1
    assert len(orch_store.list_quarantine(cfg_o.namespace)) == 1


def test_claim_and_git_error_alerts(tmp_path, monkeypatch):
    phases: list[str] = []

    def capture(cfg, phase, **_fields):
        phases.append(phase)
        return True

    monkeypatch.setattr("ia_orchestrator.loop.alert_notify", capture)
    cfg = make_cfg(tmp_path, "p-loop-al", "org/loop-al")
    cfg.alerts.enabled = True
    store = Store(tmp_path / "loop-al.sqlite")
    home = tmp_path / "home"
    env = build_envelope(
        project_id=cfg.project_id,
        repository=cfg.github.repository,
        task_id="task-1",
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.REQUEST.value,
        body="faz",
        request_id="req-1",
    )
    rendered = render_message(env, "faz")
    store.upsert_message(
        cfg.namespace,
        message_id=env.message_id,
        task_id=env.task_id,
        github_comment_id=1,
        issue_number=1,
        envelope=env,
        body="faz",
        raw=rendered,
        observed_hash="abc",
        kind="envelope",
        github_login="bot-orquestrador",
    )
    snap = tick(cfg, store, None, "executor", home, do_claim=True)
    assert snap["claimed"] is True
    assert "request_claimed" in phases

    err = tick(cfg, store, BoomEngine(), "executor", home, do_claim=True)
    assert err["status"] == STATUS_GIT_ERROR
    assert phases.count("git_error") == 1
    again = tick(cfg, store, BoomEngine(), "executor", home, do_claim=True)
    assert again["changed"] is False
    assert phases.count("git_error") == 1
