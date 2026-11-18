from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.loop import STATUS_IDLE, STATUS_JOB, STATUS_RECOVERY, inspect, tick
import json

from ia_orchestrator.protocol import Envelope, MessageType, build_envelope, new_id, render_message
from ia_orchestrator.state import TaskState, apply_transition, decision_block
from ia_orchestrator.workers import Engine

from helpers import comment_types, open_task, pair
from test_question_resume import _env, parse_type


def test_decision_block_is_result_not_completion():
    assert decision_block({"status": "blocked", "summary": "falta a branch"}) is True
    assert decision_block({"status": "blocked", "summary": "dúvida", "transient": True}) is False
    assert decision_block({"status": "success"}) is False
    assert apply_transition(TaskState.RUNNING, "result") == TaskState.WAITING_ORCHESTRATOR
    assert apply_transition(TaskState.RUNNING, "result") != TaskState.COMPLETED


def test_decision_block_releases_claim_and_waits_for_new_request(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-dec", "org/dec", shared)
    home = tmp_path / "home"
    executor = SimulatedExecutorAdapter(
        script=[
            {"status": "blocked", "summary": "falta a branch", "questions": ["Qual branch?"]},
            {
                "status": "success",
                "summary": "ok",
                "tests": [{"name": "t", "passed": True, "evidence": "e"}],
                "shared_artifacts": [{"repository": "org/dec", "path": "x", "commit": "c", "sha256": "s"}],
            },
        ]
    )
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", executor=executor, home=home)
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe.sync()
    claimed = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert claimed["status"] == STATUS_RECOVERY
    exe.tick()
    types = comment_types(et, issue.number)
    assert "result" in types
    assert "question" not in types
    assert inspect(cfg_e, es_, "executor", home)["status"] == STATUS_IDLE
    reqs = [c for c in et.list_issue_comments(issue.number) if parse_type(c.body) == "request"]
    request_env = _env(reqs[0].body)
    request_id = request_env.request_id
    assert es_.get_request(cfg_e.namespace, request_id)["status"] == "DONE"
    issue_row = et.get_issue(issue.number)
    assert issue_row.state == "open"
    assert "status:waiting-orchestrator" in issue_row.labels
    answer = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="executor",
        type=MessageType.ANSWER.value,
        body="Use main.",
        in_reply_to=request_env.message_id,
        request_id=request_id,
    )
    ot.actor = "usuario-responsavel"
    ot.create_comment(issue.number, render_message(answer, "Use main."))
    ot.actor = "bot-orquestrador"
    exe.tick()
    assert len(executor.calls) == 1
    orch.tick()
    assert os_.get_task(cfg_o.namespace, task_id)["state"] != "COMPLETED"
    assert os_.get_task(cfg_o.namespace, task_id)["state"] != "WAITING_INPUT"
    assert et.get_issue(issue.number).state == "open"
    exe.tick()
    assert len(executor.calls) == 2
    assert executor.calls[0].request_id != executor.calls[1].request_id
    assert et.get_issue(issue.number).state == "open"


def test_question_releases_running_and_accepts_a_new_request(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-tr", "org/tr", shared)
    cfg_e.executor.mode = "cursor_chat"
    home = tmp_path / "home"
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", home=home)
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe.sync()
    claimed = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert claimed["status"] == STATUS_RECOVERY
    row = next(r for r in es_.unprocessed_messages(cfg_e.namespace) if r.get("type") == "request")
    env = Envelope.model_validate(json.loads(row["envelope_json"]))
    task = es_.get_task(cfg_e.namespace, task_id)
    exe._publish_executor_output(
        task,
        env,
        {"status": "blocked", "summary": "dúvida pontual", "questions": ["Qual arquivo?"], "transient": True},
        "idem-transient",
    )
    exe.flush_outbox()
    still = inspect(cfg_e, es_, "executor", home)
    assert still["status"] == STATUS_IDLE
    assert still["running"] == []
    assert "question" in comment_types(et, issue.number)
    issue_row = et.get_issue(issue.number)
    assert issue_row.state == "open"
    assert "status:waiting-orchestrator" in issue_row.labels
    assert "status:running" not in issue_row.labels
    fresh = new_id()
    follow = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.REQUEST.value,
        body="## Objetivo\nseguir depois da question\n",
        request_id=fresh,
    )
    et.actor = "bot-orquestrador"
    et.create_comment(issue.number, render_message(follow, "## Objetivo\nseguir depois da question\n"))
    exe.sync()
    nxt = inspect(cfg_e, es_, "executor", home)
    assert nxt["status"] == STATUS_JOB
    assert nxt["head"]["request_id"] == fresh
    claimed_again = tick(cfg_e, es_, exe, "executor", home, do_claim=True)
    assert claimed_again["status"] == STATUS_RECOVERY
    assert claimed_again["running"]
    assert et.get_issue(issue.number).state == "open"
