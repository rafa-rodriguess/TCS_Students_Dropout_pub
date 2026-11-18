from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ia_orchestrator.cli import build_parser
from ia_orchestrator.errors import ProtocolError, UsageError
from ia_orchestrator.protocol import MessageType, build_envelope
from ia_orchestrator.publish import commit_and_push_transferred
from ia_orchestrator.send_file import (
    TRANSFER_DIR,
    build_spec,
    download_public_file,
    establish_public_folder,
    parse_spec,
    public_download_url,
    receive_public_file,
    render_send_file_body,
    sha256_bytes,
)
from ia_orchestrator.state import TaskState, apply_transition

from helpers import make_cfg

FOLDER = "https://drive.google.com/drive/folders/pastaPublica01?usp=sharing"
FILE = "https://drive.google.com/file/d/arquivoPublico01/view?usp=sharing"
OTHER_FOLDER = "https://drive.google.com/drive/folders/outraPasta99?usp=sharing"


def _spec(payload: bytes, **overrides: object) -> dict:
    values = dict(
        filename="artigo.pdf",
        sha256=sha256_bytes(payload),
        size=len(payload),
        folder_url=FOLDER,
        drive_url=FILE,
        push=False,
    )
    values.update(overrides)
    return build_spec(**values)  # type: ignore[arg-type]


def test_spec_stays_inside_transfered_files():
    spec = _spec(b"abcd")
    assert spec["destination"] == f"{TRANSFER_DIR}/artigo.pdf"
    assert spec["push"] is False
    assert spec["folder_id"] == "pastaPublica01"
    assert spec["file_id"] == "arquivoPublico01"
    assert "destroy_after" not in spec
    parsed = parse_spec(render_send_file_body(spec))
    assert parsed == spec
    with pytest.raises(UsageError):
        build_spec(
            filename="../segredo.pdf",
            sha256="ab" * 32,
            size=1,
            folder_url=FOLDER,
            drive_url=FILE,
        )
    forged = render_send_file_body(spec).replace(spec["destination"], "proposal/refs/segredo.pdf")
    with pytest.raises(UsageError):
        parse_spec(forged)
    with pytest.raises(UsageError):
        build_spec(
            filename="artigo.pdf",
            sha256="ab" * 32,
            size=1,
            folder_url="https://example.com/drive/folders/pastaPublica01",
            drive_url=FILE,
        )


def test_folder_link_is_recorded_once(tmp_path: Path):
    cfg = make_cfg(tmp_path, "proj-sf", "org/sf")
    home = tmp_path / "home"
    first = establish_public_folder(cfg, home, FOLDER)
    again = establish_public_folder(cfg, home, "https://drive.google.com/drive/folders/pastaPublica01")
    assert again["folder_id"] == first["folder_id"]
    with pytest.raises(UsageError):
        establish_public_folder(cfg, home, OTHER_FOLDER)


def test_download_rejects_html_and_accepts_bytes():
    payload = b"%PDF-1.4 hello"
    html = ("<html>confirm=" + "99" + "</html>").encode()

    def fetch_html_then_file(url: str) -> tuple[str, bytes]:
        if url == public_download_url("arquivoPublico01", "99"):
            return "application/pdf", payload
        return "text/html", html

    assert download_public_file("arquivoPublico01", fetch=fetch_html_then_file) == payload

    def only_html(_url: str) -> tuple[str, bytes]:
        return "text/html", b"<html>login</html>"

    with pytest.raises(UsageError):
        download_public_file("arquivoPublico01", fetch=only_html)


def test_receive_checks_folder_size_and_hash(tmp_path: Path):
    payload = b"%PDF-1.4 hello"
    spec = _spec(payload)
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def page(_url: str) -> str:
        return "lista arquivoPublico01"

    def good(_url: str) -> tuple[str, bytes]:
        return "application/pdf", payload

    outcome = receive_public_file(workspace, spec, fetch_page=page, fetch_file=good)
    assert outcome["status"] == "success"
    assert outcome["delete_from_drive"] is True
    assert (workspace / spec["destination"]).read_bytes() == payload

    def missing(_url: str) -> str:
        return "pasta vazia"

    refused = receive_public_file(workspace, _spec(b"outro", filename="b.pdf"), fetch_page=missing, fetch_file=good)
    assert refused["error"] == "arquivo não está na pasta pública"
    assert refused["delete_from_drive"] is False

    def wrong(_url: str) -> tuple[str, bytes]:
        return "application/pdf", b"nao-e-o-arquivo"

    mismatch = receive_public_file(
        workspace,
        _spec(payload, filename="c.pdf"),
        fetch_page=page,
        fetch_file=wrong,
    )
    assert mismatch["error"] == "tamanho ou hash não confere"
    assert not (workspace / TRANSFER_DIR / "c.pdf").exists()


def test_commit_and_push_only_the_received_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "GIT_AUTHOR_NAME": "ia-orchestrator",
        "GIT_AUTHOR_EMAIL": "ia-orchestrator@example.com",
        "GIT_COMMITTER_NAME": "ia-orchestrator",
        "GIT_COMMITTER_EMAIL": "ia-orchestrator@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    workspace = tmp_path / "repo"
    workspace.mkdir()
    bare = tmp_path / "bare.git"
    subprocess.check_call(["git", "init"], cwd=workspace)
    subprocess.check_call(["git", "commit", "--allow-empty", "-m", "init"], cwd=workspace)
    subprocess.check_call(["git", "init", "--bare", str(bare)])
    subprocess.check_call(["git", "remote", "add", "origin", str(bare)], cwd=workspace)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=workspace, text=True).strip()
    subprocess.check_call(["git", "push", "-u", "origin", branch], cwd=workspace)
    target_dir = workspace / TRANSFER_DIR
    target_dir.mkdir()
    (target_dir / "a.pdf").write_bytes(b"%PDF")
    (workspace / "other.txt").write_text("nao enviar", encoding="utf-8")
    report = commit_and_push_transferred(workspace, f"{TRANSFER_DIR}/a.pdf")
    assert report["pushed"] is True
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=workspace, text=True)
    assert "other.txt" in status
    assert "a.pdf" not in status
    secret = target_dir / "segredo.pdf"
    secret.write_text("ghp_" + ("a" * 24), encoding="utf-8")
    refused = commit_and_push_transferred(workspace, f"{TRANSFER_DIR}/segredo.pdf")
    assert refused["committed"] is False
    outside = commit_and_push_transferred(workspace, "proposal/refs/a.pdf")
    assert outside["reason"] == "path outside transfered_files"


def test_send_file_transitions_and_cli_aliases():
    assert apply_transition(TaskState.WAITING_ORCHESTRATOR, "send_file") == TaskState.WAITING_EXECUTOR
    assert apply_transition(TaskState.RUNNING, "send_file_ready") == TaskState.RUNNING
    with pytest.raises(ProtocolError):
        apply_transition(TaskState.RUNNING, "send_file")
    env = build_envelope(
        project_id="p",
        repository="org/repo",
        task_id="t",
        sender_role="executor",
        sender_id="exec",
        recipient_role="orchestrator",
        type=MessageType.SEND_FILE.value,
        body="x",
        request_id="r",
    )
    with pytest.raises(ProtocolError):
        env.required_fields_for_type()
    parser = build_parser()
    for argv in (
        ["send-file", "--project", "p", "--role", "orchestrator", "--folder-link", FOLDER],
        ["send_file", "--project", "p", "--role", "orchestrator", "--task", "t", "--file", "a.pdf", "--drive-url", FILE],
        ["send", "file", "--project", "p", "--role", "executor", "--task", "t", "--request", "r"],
    ):
        parsed = parser.parse_args(argv)
        assert parsed.func.__name__ == "cmd_send_file"
        assert parsed.push is False
        assert not hasattr(parsed, "destroy_after")
