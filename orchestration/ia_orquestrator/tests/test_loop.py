from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.errors import NetworkError
from ia_orchestrator.loop import (
    STATUS_CONFLICT,
    STATUS_GIT_ERROR,
    STATUS_IDLE,
    STATUS_JOB,
    STATUS_RECOVERY,
    complete_local_claim,
    inspect,
    rearm_next_wake,
    running_dir,
    tick,
)
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import MessageType, build_envelope, render_message
from ia_orchestrator.workers import Engine

from helpers import comment_types, make_cfg, open_task, pair


class BoomEngine:
    def sync(self) -> int:
        raise NetworkError("github indisponível")


def test_idle_does_not_wake(tmp_path):
    cfg = make_cfg(tmp_path, "p-idle", "org/idle")
    store = Store(tmp_path / "idle.sqlite")
    home = tmp_path / "home"
    first = tick(cfg, store, None, "executor", home, do_claim=True)
    assert first["status"] == STATUS_IDLE
    assert first["wake"] is False
    assert first["sentinel"] is None
    second = tick(cfg, store, None, "executor", home, do_claim=True)
    assert second["wake"] is False
    assert second["changed"] is False


def test_claim_one_running_dedup_and_isolation(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-loop", "org/loop", shared)
    cfg_e.executor.mode = "cursor_chat"
    home = tmp_path / "home"
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    task_id, issue, _ = open_task(ot, cfg_o, "## Objetivo\nCorrer no chat.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe = Engine(cfg_e, es_, et, "executor", home=home)
    exe.sync()
    before = inspect(cfg_e, es_, "executor", home)
    assert before["status"] == STATUS_JOB
    assert before["pending"]

    exe.tick()
    still = inspect(cfg_e, es_, "executor", home)
    assert still["status"] == STATUS_JOB
    assert still["pending"]

    first = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert first["status"] == STATUS_RECOVERY
    assert first["claimed"] is True
    assert "ack" in comment_types(et, issue.number)
    labels = et.get_issue(issue.number).labels
    assert "status:claimed" in labels
    assert "ia-orchestrator" in labels
    assert first["wake"] is True
    assert first["sentinel"]
    assert first["sentinel"].startswith("AGENT_LOOP_TICK_executor")
    assert '"status":"JOB"' in first["sentinel"]
    assert len(first["running"]) == 1
    running = running_dir(cfg_e, home)
    assert (running / first["running"][0]).is_file()

    second = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert second["status"] == STATUS_RECOVERY
    assert second["wake"] is False
    assert len(second["running"]) == 1

    request_id = first["head"]["request_id"]
    archived = complete_local_claim(cfg_e, es_, home, request_id)
    assert archived
    after = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert after["status"] == STATUS_IDLE
    assert after["wake"] is False
    assert inspect(cfg_e, es_, "executor", home)["running"] == []

    other_home = tmp_path / "home-b"
    cfg_b = make_cfg(tmp_path, "outro", "org/outro")
    store_b = Store(tmp_path / "outro.sqlite")
    isolated = inspect(cfg_b, store_b, "executor", other_home)
    assert isolated["status"] == STATUS_IDLE
    assert isolated["running"] == []


def test_rearm_next_wake_reemits_recovery_without_second_claim(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-rearm", "org/rearm", shared)
    cfg_e.executor.mode = "cursor_chat"
    home = tmp_path / "home"
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    task_id, issue, _ = open_task(ot, cfg_o, "## Objetivo\nJob multi-turn.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe = Engine(cfg_e, es_, et, "executor", home=home)
    exe.sync()
    first = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert first["status"] == STATUS_RECOVERY
    assert first["wake"] is True
    assert len(first["running"]) == 1

    quiet = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert quiet["status"] == STATUS_RECOVERY
    assert quiet["wake"] is False

    state = rearm_next_wake(cfg_e, home, "executor")
    assert state["rearmed"] is True
    assert state["had_previous_wake"] is True

    resumed = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert resumed["status"] == STATUS_RECOVERY
    assert resumed["wake"] is True
    assert resumed["claimed"] is False
    assert len(resumed["running"]) == 1
    assert resumed["sentinel"].startswith("AGENT_LOOP_TICK_executor")
    assert '"status":"RECOVERY_REQUIRED"' in resumed["sentinel"]


def test_execution_start_posts_progress_and_running_status(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-run", "org/run", shared)
    cfg_e.executor.mode = "cursor_chat"
    cfg_e.alerts.enabled = True
    home = tmp_path / "home"
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", home=home)
    task_id, issue, _ = open_task(ot, cfg_o, "## Objetivo\nComeçar.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe.sync()
    snap = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    request_id = snap["head"]["request_id"]
    phases: list[str] = []

    def capture(_cfg, phase, **_fields):
        phases.append(phase)
        return True

    exe._alert = lambda phase, **fields: capture(cfg_e, phase, **fields)  # type: ignore[method-assign]
    exe.announce_execution_started(
        es_.get_task(cfg_e.namespace, task_id),
        request_id=request_id,
        in_reply_to=snap["head"]["message_id"],
        issue=issue.number,
    )
    exe.flush_outbox()
    types = comment_types(et, issue.number)
    assert "ack" in types
    assert "progress" in types
    comments = et.list_issue_comments(issue.number)
    ack_bodies = [comment.body for comment in comments if '"type": "ack"' in comment.body or '"type":"ack"' in comment.body]
    progress_bodies = [comment.body for comment in comments if '"type": "progress"' in comment.body or '"type":"progress"' in comment.body]
    assert any("ia-orchestrator:executor-capabilities:v1" in body for body in ack_bodies)
    assert any('"util_version":"3.08"' in body for body in ack_bodies)
    assert any("ia-orchestrator:executor-capabilities:v1" in body for body in progress_bodies)
    assert "status:running" in et.get_issue(issue.number).labels
    assert "execution_started" in phases


def test_queue_conflict_and_git_error(tmp_path):
    cfg = make_cfg(tmp_path, "p-conf", "org/conf")
    store = Store(tmp_path / "conf.sqlite")
    home = tmp_path / "home"
    directory = running_dir(cfg, home)
    (directory / "one.md").write_text("a\n", encoding="utf-8")
    (directory / "two.md").write_text("b\n", encoding="utf-8")
    snap = inspect(cfg, store, "executor", home)
    assert snap["status"] == STATUS_CONFLICT
    claimed = tick(cfg, store, None, "executor", home, do_claim=True)
    assert claimed["status"] == STATUS_CONFLICT
    assert claimed["wake"] is True
    again = tick(cfg, store, None, "executor", home, do_claim=True)
    assert again["wake"] is False

    err = tick(cfg, store, BoomEngine(), "executor", home, do_claim=True)  # type: ignore[arg-type]
    assert err["status"] == STATUS_GIT_ERROR
    assert err["wake"] is True
    assert "AGENT_LOOP_TICK_executor" in (err["sentinel"] or "")


def test_cursor_chat_does_not_run_subprocess(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-skip", "org/skip", shared)
    cfg_e.executor.mode = "cursor_chat"
    adapter = SimulatedExecutorAdapter(
        script=[{"status": "success", "summary": "nao deveria correr", "tests": [], "shared_artifacts": []}]
    )
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", executor=adapter)
    task_id, issue, _ = open_task(ot, cfg_o, "## Objetivo\nNao executar no python.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    assert "request" in comment_types(ot, issue.number)
    stats = exe.tick()
    assert stats["processed"] == 0
    types = []
    for comment in et.list_issue_comments(issue.number):
        if '"type": "result"' in comment.body or '"type":"result"' in comment.body:
            types.append("result")
    assert "result" not in types


def test_recovery_wakes_for_sideband_control_without_second_running(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-control", "org/control", shared)
    cfg_e.executor.mode = "cursor_chat"
    home = tmp_path / "home"
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", home=home)

    task_id, issue, _ = open_task(ot, cfg_o, "## Objetivo\nExecução longa.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe.sync()
    primary = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert primary["status"] == STATUS_RECOVERY
    assert len(primary["running"]) == 1

    # Consume the initial wake; subsequent recovery with no control is quiet.
    quiet = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert quiet["status"] == STATUS_RECOVERY
    assert quiet["wake"] is False

    body = "Inspecione telemetria sem tocar no processo atual."
    control = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.NON_BLOCKING.value,
        body=body,
        request_id="control-nb-1",
        in_reply_to=primary["head"]["message_id"],
    )
    ot.actor = "bot-orquestrador"
    ot.create_comment(issue.number, render_message(control, body))

    woke = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert woke["status"] == STATUS_RECOVERY
    assert woke["wake"] is True
    assert len(woke["running"]) == 1
    assert woke["control_head"]["type"] == MessageType.NON_BLOCKING.value
    assert woke["control_head"]["request_id"] == "control-nb-1"
    assert "control_head" in (woke["sentinel"] or "")

    again = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert again["status"] == STATUS_RECOVERY
    assert again["wake"] is False
    assert len(again["running"]) == 1



def test_non_blocking_control_result_wakes_orchestrator_immediately(tmp_path):
    cfg = make_cfg(tmp_path, "proj-control-result", "org/control-result")
    store = Store(tmp_path / "control-result.sqlite")
    home = tmp_path / "home"
    task_id = "task-control-result"
    store.upsert_task(
        cfg.namespace,
        task_id,
        issue_number=7,
        title="control",
        state="RUNNING",
    )

    body = '{"status":"success","summary":"still running"}'
    env = build_envelope(
        project_id=cfg.project_id,
        repository=cfg.github.repository,
        task_id=task_id,
        sender_role="executor",
        sender_id="bot-executor",
        recipient_role="orchestrator",
        type=MessageType.CONTROL_RESULT.value,
        body=body,
        request_id="control-1",
        in_reply_to="non-blocking-message",
    )
    store.upsert_message(
        cfg.namespace,
        message_id=env.message_id,
        task_id=task_id,
        github_comment_id=101,
        issue_number=7,
        envelope=env,
        body=body,
        raw=render_message(env, body),
        observed_hash="hash",
        kind="envelope",
        github_login="bot-executor",
    )

    snapshot = tick(cfg, store, None, "orchestrator", home, do_claim=True)
    assert snapshot["status"] == STATUS_RECOVERY
    assert snapshot["wake_status"] == STATUS_JOB
    assert snapshot["wake"] is True
    assert snapshot["head"]["type"] == MessageType.CONTROL_RESULT.value
    assert snapshot["head"]["request_id"] == "control-1"

def test_sideband_control_without_primary_run_wakes_but_is_not_claimed(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-orphan-control", "org/orphan-control", shared)
    cfg_e.executor.mode = "cursor_chat"
    home = tmp_path / "home"
    task_id, issue, opened = open_task(ot, cfg_o, "## Objetivo\nPrimário.\n")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")

    body = "telemetria"
    control = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.NON_BLOCKING.value,
        body=body,
        request_id="orphan-control-1",
        in_reply_to=opened.message_id,
    )
    ot.actor = "bot-orquestrador"
    ot.create_comment(issue.number, render_message(control, body))

    exe = Engine(cfg_e, es_, et, "executor", home=home)
    snap = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert snap["status"] == STATUS_JOB
    assert snap["wake"] is True
    assert snap["control_head"]["request_id"] == "orphan-control-1"
    assert snap["running"] == []
    assert snap["claimed"] is False
