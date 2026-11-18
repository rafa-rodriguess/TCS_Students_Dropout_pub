from __future__ import annotations

import json
import os

from ia_orchestrator.cli import build_parser, main
from ia_orchestrator.config import resolve_project


def test_cli_bootstrap_doctor_dry_run_and_demo(tmp_path, capsys):
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    ws.mkdir()
    env_home = str(home)
    rc = main(["--home", env_home, "bootstrap", "--project", "exemplo", "--repo", "organizacao/repositorio", "--workspace", str(ws)])
    assert rc == 0
    cfg = resolve_project("exemplo", home)
    assert cfg.github.repository == "organizacao/repositorio"
    rc = main(["--home", env_home, "--json", "project", "list"])
    assert rc == 0
    os.environ["GITHUB_TOKEN_EXEMPLO"] = "dummy-not-a-real-token"
    rc = main(["--home", env_home, "--json", "doctor", "--project", "exemplo"])
    assert rc == 0
    prompt = tmp_path / "prompt.md"
    prompt.write_text("## Objetivo\nTeste dry-run\n", encoding="utf-8")
    rc = main(["--home", env_home, "--json", "task", "create", "--project", "exemplo", "--prompt-file", str(prompt), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry_run" in out
    demo_dir = tmp_path / "demo"
    rc = main(["demo", "offline", "--output", str(demo_dir)])
    assert rc == 0
    rc = main(["--home", env_home, "--json", "loop", "arm", "--project", "exemplo", "--role", "executor"])
    assert rc == 0
    arm_out = capsys.readouterr().out
    assert "AGENT_LOOP_TICK_executor" in arm_out
    assert "block_until_ms" in arm_out or "notify_on_output" in arm_out


def test_cli_requires_project(capsys):
    rc = main(["project", "show"])
    assert rc != 0



def test_cli_exposes_passive_check_and_direct_non_blocking():
    parser = build_parser()

    check = parser.parse_args(["check", "--project", "p", "--task", "t"])
    assert check.project == "p"
    assert check.task == "t"
    assert check.func.__name__ == "cmd_check"

    control = parser.parse_args([
        "message", "post",
        "--project", "p",
        "--task", "t",
        "--type", "non_blocking",
        "--recipient", "executor",
        "--request-id", "control-1",
        "--body", "telemetria read-only",
        "--sender-role", "orchestrator",
    ])
    assert control.type == "non_blocking"
    assert control.request_id == "control-1"
    assert control.func.__name__ == "cmd_message_post"

    rearm = parser.parse_args(["loop", "rearm", "--project", "p", "--role", "executor"])
    assert rearm.project == "p"
    assert rearm.role == "executor"
    assert rearm.func.__name__ == "cmd_loop_rearm"

    for argv in (
        ["pending", "--project", "p", "--role", "agent"],
        ["loop", "inspect", "--project", "p", "--role", "agent"],
        ["loop", "tick", "--project", "p", "--role", "agent", "--no-claim"],
        ["loop", "rearm", "--project", "p", "--role", "agent"],
        ["loop", "arm", "--project", "p", "--role", "agent"],
    ):
        parsed = parser.parse_args(argv)
        assert parsed.role == "agent"


def test_cli_exposes_status_command():
    parser = build_parser()
    status = parser.parse_args(["status", "--project", "p", "--task", "t"])
    assert status.project == "p"
    assert status.task == "t"
    assert status.dry_run is False
    assert status.func.__name__ == "cmd_status"
