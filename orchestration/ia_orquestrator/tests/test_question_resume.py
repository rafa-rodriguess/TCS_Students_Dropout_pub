from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.protocol import MessageType, build_envelope, render_message
from ia_orchestrator.workers import Engine

from helpers import comment_types, open_task, pair


def test_question_answer_resumes_same_request(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-q", "org/q", shared)
    model = SimulatedModelAdapter()
    executor = SimulatedExecutorAdapter(
        script=[
            {"status": "blocked", "summary": "dúvida", "questions": ["Qual branch?"], "transient": True},
            {
                "status": "success",
                "summary": "ok",
                "tests": [{"name": "t", "passed": True, "evidence": "e"}],
                "shared_artifacts": [{"repository": "org/q", "path": "x", "commit": "c", "sha256": "s"}],
            },
        ]
    )
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=model)
    exe = Engine(cfg_e, es_, et, "executor", executor=executor)
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    for _ in range(4):
        orch.tick()
        exe.tick()
    types = comment_types(ot, issue.number)
    assert "question" in types
    task = os_.get_task(cfg_o.namespace, task_id)
    assert task["state"] == "WAITING_INPUT"
    reqs = [c for c in ot.list_issue_comments(issue.number) if parse_type(c.body) == "request"]
    assert reqs
    request_env = _env(reqs[0].body)
    # resposta humana à pergunta, retomando a mesma request
    q = [c for c in ot.list_issue_comments(issue.number) if parse_type(c.body) == "question"][0]
    qenv = _env(q.body)
    body = "Use a branch main."
    ans = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="executor",
        type=MessageType.ANSWER.value,
        body=body,
        in_reply_to=qenv.message_id,
        request_id=request_env.request_id,
    )
    ot.actor = "usuario-responsavel"
    ot.create_comment(issue.number, render_message(ans, body))
    ot.actor = "bot-orquestrador"
    for _ in range(6):
        orch.tick()
        exe.tick()
    assert len(executor.calls) == 2
    assert executor.calls[0].request_id == executor.calls[1].request_id == request_env.request_id
    assert os_.get_task(cfg_o.namespace, task_id)["state"] == "COMPLETED"


def parse_type(body: str) -> str | None:
    from ia_orchestrator.protocol import parse_comment

    p = parse_comment(body)
    return p.envelope.type if p.envelope else None


def _env(body: str):
    from ia_orchestrator.protocol import parse_comment

    return parse_comment(body).envelope
