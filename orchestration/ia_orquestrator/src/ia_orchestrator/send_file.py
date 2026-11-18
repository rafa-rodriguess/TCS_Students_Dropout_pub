"""Transferência send_file pela pasta pública do Google Drive.

A primeira utilização grava o link público da pasta. A orquestradora sobe o
arquivo nessa pasta e publica o link do arquivo, o SHA-256 e o tamanho. A
executora baixa, confere e grava só em transfered_files/. Quem apaga o arquivo
da pasta é a orquestradora, depois do result de sucesso. push default é false.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from ia_orchestrator.config import data_dir
from ia_orchestrator.errors import UsageError
from ia_orchestrator.protocol import MessageType, new_id

TRANSFER_DIR = "transfered_files"
MAX_BYTES = 200 * 1024 * 1024
_BUSY_LABELS = {"status:running", "status:claimed"}
_ALLOWED_HOSTS = frozenset({"drive.google.com", "drive.usercontent.google.com", "docs.google.com"})
_FOLDER_PATH = re.compile(r"^/drive(?:/u/\d+)?/folders/([A-Za-z0-9_-]+)/?$")
_FILE_PATH = re.compile(r"^/file/d/([A-Za-z0-9_-]+)(?:/.*)?$")


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    if name != filename or not name or name in {".", ".."} or name.startswith("."):
        raise UsageError("nome de arquivo inválido")
    if "/" in name or "\\" in name or ".." in name:
        raise UsageError("nome de arquivo inválido")
    if any(ord(char) < 32 for char in name):
        raise UsageError("nome de arquivo inválido")
    return name


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if size > MAX_BYTES:
        raise UsageError("arquivo acima do limite de 200 MiB")
    return digest.hexdigest(), size


def parse_drive_id(url: str, kind: str) -> str:
    text = (url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != "drive.google.com":
        raise UsageError("link público do Drive inválido")
    query = parse_qs(parsed.query)
    if kind == "folder":
        match = _FOLDER_PATH.fullmatch(parsed.path)
        if match:
            return match.group(1)
        if parsed.path.rstrip("/") == "/folderview" and query.get("id"):
            return query["id"][0]
    elif kind == "file":
        match = _FILE_PATH.fullmatch(parsed.path)
        if match:
            return match.group(1)
        if parsed.path.rstrip("/") in {"/open", "/uc"} and query.get("id"):
            return query["id"][0]
    else:
        raise UsageError("tipo de link do Drive inválido")
    raise UsageError("link público do Drive inválido")


def canonical_folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"


def canonical_file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


def build_spec(
    *,
    filename: str,
    sha256: str,
    size: int,
    folder_url: str,
    drive_url: str,
    push: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    name = safe_filename(filename)
    if size < 0 or size > MAX_BYTES:
        raise UsageError("tamanho de arquivo inválido")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise UsageError("sha256 inválido")
    folder_id = parse_drive_id(folder_url, "folder")
    file_id = parse_drive_id(drive_url, "file")
    return {
        "filename": name,
        "sha256": sha256,
        "bytes": int(size),
        "destination": f"{TRANSFER_DIR}/{name}",
        "folder_url": canonical_folder_url(folder_id),
        "folder_id": folder_id,
        "drive_url": canonical_file_url(file_id),
        "file_id": file_id,
        "push": bool(push),
        "overwrite": bool(overwrite),
    }


def extract_json(body: str) -> dict[str, Any]:
    text = body or ""
    fence = text.find("```json")
    if fence >= 0:
        text = text[fence + len("```json") :]
        end = text.find("```")
        if end >= 0:
            text = text[:end]
    start = text.find("{")
    if start < 0:
        raise UsageError("corpo sem JSON")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise UsageError("JSON inválido") from exc
    if not isinstance(data, dict):
        raise UsageError("JSON inválido")
    return data


def parse_spec(body: str) -> dict[str, Any]:
    data = extract_json(body)
    spec = build_spec(
        filename=str(data.get("filename") or ""),
        sha256=str(data.get("sha256") or ""),
        size=int(data.get("bytes")),
        folder_url=str(data.get("folder_url") or ""),
        drive_url=str(data.get("drive_url") or ""),
        push=bool(data.get("push", False)),
        overwrite=bool(data.get("overwrite", False)),
    )
    if data.get("destination") != spec["destination"]:
        raise UsageError("destino fora de transfered_files")
    if data.get("folder_id") not in {None, spec["folder_id"]}:
        raise UsageError("pasta pública não confere com o link")
    if data.get("file_id") not in {None, spec["file_id"]}:
        raise UsageError("arquivo público não confere com o link")
    return spec


def render_send_file_body(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, indent=2, ensure_ascii=False)
    return f"## SEND_FILE\n\n```json\n{payload}\n```\n"


def render_result_body(outcome: dict[str, Any]) -> str:
    payload = json.dumps(outcome, indent=2, ensure_ascii=False)
    return f"## RESULTADO send_file\n\n```json\n{payload}\n```\n"


def control_dir(cfg: Any, home: Path | None) -> Path:
    return data_dir(cfg, home) / "send_file"


def folder_record_path(cfg: Any, home: Path | None) -> Path:
    return control_dir(cfg, home) / "folder.json"


def load_folder(cfg: Any, home: Path | None) -> dict[str, Any] | None:
    path = folder_record_path(cfg, home)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("folder_id"):
        raise UsageError("registro da pasta pública está inválido")
    return data


def establish_public_folder(cfg: Any, home: Path | None, folder_url: str) -> dict[str, Any]:
    folder_id = parse_drive_id(folder_url, "folder")
    current = load_folder(cfg, home)
    if current is not None and current["folder_id"] != folder_id:
        raise UsageError("a pasta pública já está definida e o link é outro")
    if current is not None:
        return current
    record = {
        "folder_id": folder_id,
        "folder_url": canonical_folder_url(folder_id),
        "established_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path = folder_record_path(cfg, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return record


class _DriveRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        parsed = urlparse(newurl)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in _ALLOWED_HOSTS:
            raise UsageError("o download saiu do Google Drive")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def _open_drive(url: str, timeout: float = 60) -> tuple[str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "ia-orchestrator-send-file"})
    opener = urllib.request.build_opener(_DriveRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise UsageError(f"download público falhou com HTTP {exc.code}") from exc
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"download público falhou: {exc}") from exc
    if len(payload) > MAX_BYTES:
        raise UsageError("arquivo acima do limite de 200 MiB")
    return content_type, payload


def fetch_text(url: str) -> str:
    _content_type, payload = _open_drive(url)
    return payload.decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> tuple[str, bytes]:
    return _open_drive(url)


def public_download_url(file_id: str, confirm: str = "t") -> str:
    return (
        "https://drive.usercontent.google.com/download"
        f"?id={quote(file_id)}&export=download&confirm={quote(confirm)}"
    )


def _is_html(content_type: str, payload: bytes) -> bool:
    if "text/html" in content_type.lower():
        return True
    return payload.lstrip().startswith((b"<!doctype", b"<!DOCTYPE", b"<html", b"<HTML"))


def download_public_file(file_id: str, *, fetch: Callable[[str], tuple[str, bytes]] = fetch_bytes) -> bytes:
    content_type, payload = fetch(public_download_url(file_id))
    if _is_html(content_type, payload):
        text = payload.decode("utf-8", errors="replace")
        confirm = re.search(r"confirm=([0-9A-Za-z_-]+)", text)
        if confirm and confirm.group(1) != "t":
            content_type, payload = fetch(public_download_url(file_id, confirm.group(1)))
    if _is_html(content_type, payload):
        raise UsageError("o link público devolveu HTML, não o arquivo")
    return payload


def folder_lists_file(folder_id: str, file_id: str, *, fetch: Callable[[str], str] = fetch_text) -> bool:
    page = fetch(canonical_folder_url(folder_id))
    return file_id in page


def receive_public_file(
    workspace: Path,
    spec: dict[str, Any],
    *,
    fetch_page: Callable[[str], str] = fetch_text,
    fetch_file: Callable[[str], tuple[str, bytes]] = fetch_bytes,
) -> dict[str, Any]:
    destination = (workspace / spec["destination"]).resolve()
    root = (workspace / TRANSFER_DIR).resolve()
    if destination.parent != root:
        raise UsageError("destino fora de transfered_files")
    if destination.exists() and not spec["overwrite"]:
        return {"status": "failed", "error": "arquivo já existe", "path": spec["destination"], "delete_from_drive": False}
    if not folder_lists_file(spec["folder_id"], spec["file_id"], fetch=fetch_page):
        return {
            "status": "failed",
            "error": "arquivo não está na pasta pública",
            "path": spec["destination"],
            "delete_from_drive": False,
        }
    try:
        payload = download_public_file(spec["file_id"], fetch=fetch_file)
    except UsageError as exc:
        return {"status": "failed", "error": str(exc), "path": spec["destination"], "delete_from_drive": False}
    if len(payload) != int(spec["bytes"]) or sha256_bytes(payload) != spec["sha256"]:
        return {
            "status": "failed",
            "error": "tamanho ou hash não confere",
            "path": spec["destination"],
            "delete_from_drive": False,
        }
    root.mkdir(parents=True, exist_ok=True)
    partial = root / f".{destination.name}.partial"
    try:
        partial.write_bytes(payload)
        if sha256_file(partial)[0] != spec["sha256"]:
            raise UsageError("releitura do arquivo não confere")
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        return {"status": "failed", "error": "falha ao gravar", "path": spec["destination"], "delete_from_drive": False}
    return {
        "status": "success",
        "sha256": spec["sha256"],
        "bytes": spec["bytes"],
        "path": spec["destination"],
        "drive_url": spec["drive_url"],
        "folder_url": spec["folder_url"],
        "delete_from_drive": True,
    }


def _other_running(cfg: Any, home: Path | None, request_id: str) -> list[str]:
    from ia_orchestrator.loop import list_running_md, running_dir

    names = []
    for path in list_running_md(running_dir(cfg, home, "executor")):
        text = path.read_text(encoding="utf-8")
        if f"request_id: {request_id}" not in text:
            names.append(path.name)
    return names


def _deliver(engine: Any, task: dict[str, Any], env: Any, outcome: dict[str, Any]) -> None:
    from ia_orchestrator.issue_status import STATUS_WAITING_ORCHESTRATOR
    from ia_orchestrator.loop import complete_local_claim

    engine._publish(
        task,
        MessageType.RESULT.value,
        render_result_body(outcome),
        recipient="orchestrator",
        request_id=env.request_id,
        in_reply_to=env.message_id,
    )
    engine.set_issue_status(task.get("issue_number"), STATUS_WAITING_ORCHESTRATOR)
    engine.flush_outbox()
    complete_local_claim(engine.cfg, engine.store, engine.home, str(env.request_id))


def perform_executor_send_file(engine: Any, home: Path | None, env: Any, body: str) -> dict[str, Any]:
    cfg = engine.cfg
    task = engine.store.get_task(cfg.namespace, env.task_id)
    if task is None:
        raise UsageError("tarefa não encontrada")
    if _other_running(cfg, home, str(env.request_id)):
        outcome = {"status": "failed", "error": "executor ocupado com outro job", "delete_from_drive": False}
        _deliver(engine, task, env, outcome)
        return outcome
    try:
        spec = parse_spec(body)
        establish_public_folder(cfg, home, spec["folder_url"])
    except (UsageError, TypeError, ValueError) as exc:
        outcome = {"status": "failed", "error": str(exc), "delete_from_drive": False}
        _deliver(engine, task, env, outcome)
        return outcome
    engine.announce_request_claimed(
        task,
        request_id=str(env.request_id),
        in_reply_to=env.message_id,
        issue=task.get("issue_number"),
        discord=False,
    )
    engine.announce_execution_started(
        task,
        request_id=str(env.request_id),
        in_reply_to=env.message_id,
        issue=task.get("issue_number"),
    )
    engine.flush_outbox()
    try:
        outcome = receive_public_file(cfg.workspace_root(), spec)
    except Exception as exc:  # noqa: BLE001 — a issue precisa receber o fracasso
        outcome = {"status": "failed", "error": str(exc), "path": spec["destination"], "delete_from_drive": False}
    push_report: dict[str, Any] = {"committed": False, "pushed": False, "reason": "push false"}
    if outcome.get("status") == "success" and spec["push"]:
        from ia_orchestrator.publish import commit_and_push_transferred

        push_report = commit_and_push_transferred(cfg.workspace_root(), spec["destination"])
    outcome["push"] = push_report
    if spec["push"] and outcome.get("status") == "success" and not push_report.get("pushed"):
        outcome["push_error"] = push_report.get("reason")
    _deliver(engine, task, env, outcome)
    return outcome


def _issue_busy(engine: Any, task: dict[str, Any]) -> bool:
    issue_number = task.get("issue_number")
    if not issue_number:
        return False
    issue = engine.transport.get_issue(int(issue_number))
    return any(label in _BUSY_LABELS for label in (issue.labels or []))


def _wait_message(engine: Any, task_id: str, request_id: str, type_: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        engine.sync()
        rows = [
            row
            for row in engine.store.messages_for_task(engine.cfg.namespace, task_id)
            if row.get("type") == type_ and row.get("request_id") == request_id
        ]
        if rows:
            return rows[-1]
        time.sleep(0.5)
    raise UsageError(f"tempo esgotado à espera de {type_}")


def orchestrator_send_file(
    *,
    file_path: Path,
    name: str | None,
    folder_url: str,
    drive_url: str,
    push: bool,
    overwrite: bool,
) -> dict[str, Any]:
    if not file_path.is_file():
        raise UsageError("arquivo de origem não encontrado")
    digest, size = sha256_file(file_path)
    spec = build_spec(
        filename=name or file_path.name,
        sha256=digest,
        size=size,
        folder_url=folder_url,
        drive_url=drive_url,
        push=push,
        overwrite=overwrite,
    )
    return {"spec": spec, "source": str(file_path)}


def publish_orchestrator_send_file(engine: Any, task: dict[str, Any], spec: dict[str, Any]) -> Any:
    if _issue_busy(engine, task):
        raise UsageError("send-file espera a executora IDLE; a issue tem execução activa")
    request_id = new_id()
    env = engine._publish(
        task,
        MessageType.SEND_FILE.value,
        render_send_file_body(spec),
        recipient="executor",
        request_id=request_id,
    )
    engine.flush_outbox()
    return env


def wait_executor_result(engine: Any, *, task_id: str, request_id: str, timeout: float) -> dict[str, Any]:
    row = _wait_message(engine, task_id, request_id, MessageType.RESULT.value, timeout)
    result = extract_json(row.get("body_text") or "")
    return {"result": result, "delete_from_drive": result.get("status") == "success" and bool(result.get("delete_from_drive"))}
