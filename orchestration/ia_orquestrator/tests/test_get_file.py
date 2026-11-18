from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from ia_orchestrator.cli import build_parser
from ia_orchestrator.errors import ProtocolError, UsageError
from ia_orchestrator.get_file import (
    assert_public_host,
    build_request,
    canonical_source_url,
    collect_received_file,
    download_source,
    parse_request,
    read_project_git_file,
    render_get_file_body,
    sha256_bytes,
    stage_public_upload,
)
from ia_orchestrator.state import TaskState, apply_transition

FOLDER = "https://drive.google.com/drive/folders/pastaPublica01?usp=sharing"
SOURCE = "https://example.com/artigos/artigo.pdf"


def test_github_web_url_becomes_raw_file():
    raw = canonical_source_url("https://github.com/org/repo/blob/main/docs/artigo.pdf")
    assert raw == "https://raw.githubusercontent.com/org/repo/main/docs/artigo.pdf"
    spec = build_request(source_url="https://github.com/org/repo/raw/main/docs/artigo.pdf", folder_url=FOLDER)
    assert spec["source_url"] == raw
    assert spec["filename"] == "artigo.pdf"
    assert spec["folder_id"] == "pastaPublica01"
    assert parse_request(render_get_file_body(spec)) == spec


def test_source_url_rejects_non_public_targets():
    with pytest.raises(UsageError):
        build_request(source_url="http://example.com/artigo.pdf", folder_url=FOLDER)
    with pytest.raises(UsageError):
        build_request(source_url="https://user:secret@example.com/artigo.pdf", folder_url=FOLDER)
    with pytest.raises(UsageError):
        build_request(source_url="file:///etc/passwd", folder_url=FOLDER)
    with pytest.raises(UsageError):
        build_request(source_url="https://127.0.0.1/artigo.pdf", folder_url=FOLDER)
    with pytest.raises(UsageError):
        assert_public_host("10.1.1.1")

    def private(_host, _port, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.8", 443))]

    original = socket.getaddrinfo
    socket.getaddrinfo = private
    try:
        with pytest.raises(UsageError):
            assert_public_host("intranet.example")
    finally:
        socket.getaddrinfo = original


def test_html_page_is_not_uploaded(tmp_path: Path):
    spec = build_request(source_url=SOURCE, folder_url=FOLDER)
    calls: list[tuple] = []

    def fetch(_url: str):
        return "text/html", b"<html>login</html>"

    def upload(*args, **kwargs):
        calls.append((args, kwargs))
        return "arquivoNovo01"

    outcome = stage_public_upload(spec, fetch=fetch, upload=upload)
    assert outcome["status"] == "failed"
    assert outcome["delete_from_drive"] is False
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_stage_uploads_from_temp_and_reports_name():
    payload = b"%PDF-1.7 artigo"
    spec = build_request(source_url=SOURCE, folder_url=FOLDER, sha256=sha256_bytes(payload))
    seen: dict[str, object] = {}

    def fetch(_url: str):
        assert _url == SOURCE
        return "application/pdf", payload

    def upload(folder_id, filename, body, token=None):
        seen["folder_id"] = folder_id
        seen["filename"] = filename
        seen["body"] = body
        seen["token"] = token
        return "arquivoNovo01"

    outcome = stage_public_upload(spec, fetch=fetch, upload=upload, token="token-teste")
    assert outcome["status"] == "success"
    assert outcome["filename"] == "artigo.pdf"
    assert outcome["sha256"] == sha256_bytes(payload)
    assert outcome["bytes"] == len(payload)
    assert outcome["file_id"] == "arquivoNovo01"
    assert outcome["source_protocol"] == "https"
    assert outcome["delete_from_drive"] is True
    assert seen == {
        "folder_id": "pastaPublica01",
        "filename": "artigo.pdf",
        "body": payload,
        "token": "token-teste",
    }


def test_hash_mismatch_does_not_upload():
    spec = build_request(source_url=SOURCE, folder_url=FOLDER, sha256="ab" * 32)

    def fetch(_url: str):
        return "application/pdf", b"outro"

    def upload(*_args, **_kwargs):
        raise AssertionError("não deve enviar")

    outcome = stage_public_upload(spec, fetch=fetch, upload=upload)
    assert outcome["status"] == "failed"
    assert "hash" in outcome["error"]


def test_orchestrator_collects_then_deletes(tmp_path: Path):
    payload = b"conteudo"
    result = {
        "status": "success",
        "filename": "artigo.pdf",
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "file_id": "arquivoNovo01",
        "delete_from_drive": True,
    }
    deleted: list[str] = []
    output = tmp_path / "artigo.pdf"
    collected = collect_received_file(result, output, fetch=lambda _file_id: payload, delete=deleted.append)
    assert collected["status"] == "success"
    assert collected["deleted"] is True
    assert output.read_bytes() == payload
    assert deleted == ["arquivoNovo01"]


def test_get_file_transition_and_cli_aliases():
    assert apply_transition(TaskState.WAITING_ORCHESTRATOR, "get_file") == TaskState.WAITING_EXECUTOR
    with pytest.raises(ProtocolError):
        apply_transition(TaskState.RUNNING, "get_file")
    for argv in (
        ["get-file", "--project", "p", "--role", "orchestrator", "--task", "t", "--url", SOURCE],
        ["get_file", "--project", "p", "--role", "executor", "--task", "t", "--request", "r"],
        ["get", "file", "--project", "p", "--role", "orchestrator", "--task", "t", "--url", SOURCE],
    ):
        parsed = build_parser().parse_args(argv)
        assert parsed.func.__name__ == "cmd_get_file"


def _commit_file(root: Path, relative: str, payload: bytes) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    subprocess.run(["git", "add", "--", relative], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "add"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_project_file_prefers_git_over_http(tmp_path: Path):
    payload = b"%PDF-1.4 via git"
    repo = _commit_file(tmp_path, "proposal/refs/artigo.pdf", payload)
    web = "https://github.com/org/repo/blob/main/proposal/refs/artigo.pdf"
    spec = build_request(source_url=web, folder_url=FOLDER)
    assert spec["source_url"] == "https://raw.githubusercontent.com/org/repo/main/proposal/refs/artigo.pdf"

    def fetch(_url: str):
        raise AssertionError("não deve usar http")

    def upload(_folder_id, _filename, body, token=None):
        assert body == payload
        assert token == "token-teste"
        return "arquivoNovo01"

    outcome = stage_public_upload(
        spec,
        fetch=fetch,
        upload=upload,
        token="token-teste",
        workspace=repo,
        repository="org/repo",
    )
    assert outcome["status"] == "success"
    assert outcome["source_protocol"] == "git"
    assert outcome["sha256"] == sha256_bytes(payload)
    assert read_project_git_file(web, workspace=repo, repository="ORG/REPO") == payload


def test_other_repository_keeps_http(tmp_path: Path):
    payload = b"%PDF-1.4 local"
    repo = _commit_file(tmp_path, "proposal/refs/artigo.pdf", payload)
    spec = build_request(source_url="https://github.com/org/outro/blob/main/proposal/refs/artigo.pdf", folder_url=FOLDER)
    remote = b"%PDF-1.4 http"

    def fetch(_url: str):
        return "application/pdf", remote

    def upload(_folder_id, _filename, body, token=None):
        assert body == remote
        return "arquivoNovo01"

    outcome = stage_public_upload(
        spec,
        fetch=fetch,
        upload=upload,
        token="token-teste",
        workspace=repo,
        repository="org/repo",
    )
    assert outcome["source_protocol"] == "https"
    assert read_project_git_file(
        "https://github.com/org/repo/blob/main/../segredo",
        workspace=repo,
        repository="org/repo",
    ) is None


def test_missing_project_file_falls_back_to_http(tmp_path: Path):
    repo = _commit_file(tmp_path, "proposal/refs/artigo.pdf", b"local")
    spec = build_request(source_url="https://github.com/org/repo/blob/main/ausente.pdf", folder_url=FOLDER)
    remote = b"baixado"

    def fetch(_url: str):
        return "application/pdf", remote

    outcome = stage_public_upload(
        spec,
        fetch=fetch,
        upload=lambda *_args, **_kwargs: "arquivoNovo01",
        token="token-teste",
        workspace=repo,
        repository="org/repo",
    )
    assert outcome["status"] == "success"
    assert outcome["source_protocol"] == "https"
    assert outcome["sha256"] == sha256_bytes(remote)


def test_html_download_is_refused():
    with pytest.raises(UsageError):
        download_source(SOURCE, fetch=lambda _url: ("text/html", b"<!DOCTYPE html><html></html>"))
