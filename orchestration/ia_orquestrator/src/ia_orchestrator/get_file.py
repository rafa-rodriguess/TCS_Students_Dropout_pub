"""Pedido get_file: a executora busca um arquivo e o deixa na pasta do Drive.

A orquestradora publica o URL. Se esse URL aponta para um arquivo do
repositório do projeto, a executora lê o blob pelo Git. Caso contrário, baixa
o URL https para um diretório temporário. Em seguida envia o arquivo à pasta
pública já gravada e responde com o nome, o link, o SHA-256 e o tamanho. A
orquestradora baixa essa cópia e a apaga. A executora não grava o arquivo no
repositório e não apaga nada no Drive.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from ia_orchestrator.config import data_dir
from ia_orchestrator.errors import UsageError
from ia_orchestrator.protocol import MessageType, new_id
from ia_orchestrator.send_file import (
    MAX_BYTES,
    _is_html,
    _issue_busy,
    _other_running,
    canonical_file_url,
    canonical_folder_url,
    download_public_file,
    establish_public_folder,
    extract_json,
    load_folder,
    safe_filename,
    sha256_bytes,
    sha256_file,
)

_GITHUB_WEB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/([^/]+)/(.+)$")
_GITHUB_RAW = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$")
_GIT_REF = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def canonical_source_url(url: str) -> str:
    text = (url or "").strip()
    match = _GITHUB_WEB.match(text)
    if not match:
        return text
    owner, repo, ref, path = match.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


def github_repo_path(url: str) -> tuple[str, str, str, str] | None:
    parsed = urlparse((url or "").strip())
    cleaned = parsed._replace(query="", fragment="").geturl()
    match = _GITHUB_WEB.match(cleaned) or _GITHUB_RAW.match(cleaned)
    if not match:
        return None
    owner, repo, ref, path = match.groups()
    return owner, repo, ref, unquote(path)


def _safe_git_path(path: str) -> str | None:
    parts = [part for part in unquote(path).replace("\\", "/").split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def read_project_git_file(url: str, *, workspace: Path, repository: str) -> bytes | None:
    """Lê o blob se o URL for um arquivo deste repositório. None devolve a busca http."""
    located = github_repo_path(url)
    if located is None:
        return None
    owner, repo, ref, path = located
    if f"{owner}/{repo}".casefold() != repository.strip().casefold():
        return None
    if not _GIT_REF.fullmatch(ref):
        return None
    git_path = _safe_git_path(path)
    if git_path is None:
        return None
    spec = f"{ref}:{git_path}"
    try:
        probe = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "-s", spec],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    try:
        size = int(probe.stdout.strip())
    except ValueError:
        return None
    if size <= 0 or size > MAX_BYTES:
        raise UsageError("arquivo de origem vazio ou acima do limite de 200 MiB")
    try:
        blob = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "blob", spec],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if blob.returncode != 0 or len(blob.stdout) != size:
        return None
    return blob.stdout


def filename_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    return safe_filename(name)


def validate_source_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise UsageError("source_url deve ser https público")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise UsageError("source_url não é um endereço público")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise UsageError("source_url não é um endereço público")
    return parsed.geturl()


def assert_public_host(hostname: str) -> None:
    host = (hostname or "").strip().lower()
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UsageError("source_url não resolve") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or any(not ip.is_global for ip in addresses):
        raise UsageError("source_url não é um endereço público")


def build_request(
    *,
    source_url: str,
    folder_url: str,
    filename: str | None = None,
    sha256: str | None = None,
    size: int | None = None,
) -> dict[str, Any]:
    source = validate_source_url(canonical_source_url(source_url))
    name = safe_filename(filename) if filename else filename_from_url(source)
    if sha256 is not None and (len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256)):
        raise UsageError("sha256 inválido")
    if size is not None and (size < 0 or size > MAX_BYTES):
        raise UsageError("tamanho de arquivo inválido")
    from ia_orchestrator.send_file import parse_drive_id

    folder_id = parse_drive_id(folder_url, "folder")
    spec: dict[str, Any] = {
        "filename": name,
        "source_url": source,
        "folder_url": canonical_folder_url(folder_id),
        "folder_id": folder_id,
    }
    if sha256 is not None:
        spec["sha256"] = sha256
    if size is not None:
        spec["bytes"] = int(size)
    return spec


def parse_request(body: str) -> dict[str, Any]:
    data = extract_json(body)
    spec = build_request(
        source_url=str(data.get("source_url") or ""),
        folder_url=str(data.get("folder_url") or ""),
        filename=str(data["filename"]) if data.get("filename") else None,
        sha256=str(data["sha256"]) if data.get("sha256") else None,
        size=int(data["bytes"]) if data.get("bytes") is not None else None,
    )
    if data.get("filename") not in {None, spec["filename"]}:
        raise UsageError("nome de arquivo inválido")
    if data.get("folder_id") not in {None, spec["folder_id"]}:
        raise UsageError("pasta pública não confere com o link")
    return spec


def render_get_file_body(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, indent=2, ensure_ascii=False)
    return f"## GET_FILE\n\n```json\n{payload}\n```\n"


def render_result_body(outcome: dict[str, Any]) -> str:
    payload = json.dumps(outcome, indent=2, ensure_ascii=False)
    return f"## RESULTADO get_file\n\n```json\n{payload}\n```\n"


def drive_access_token() -> str | None:
    env = os.environ.get("IA_ORCHESTRATOR_DRIVE_TOKEN", "").strip()
    if env:
        return env
    path = Path.home() / ".ia_orchestrator" / "drive_token"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


class _PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        parsed = urlparse(newurl)
        validate_source_url(newurl)
        assert_public_host(parsed.hostname or "")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def fetch_source_bytes(url: str, timeout: float = 60) -> tuple[str, bytes]:
    parsed = urlparse(url)
    assert_public_host(parsed.hostname or "")
    request = urllib.request.Request(url, headers={"User-Agent": "ia-orchestrator-get-file"})
    opener = urllib.request.build_opener(_PublicRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise UsageError(f"download da origem falhou com HTTP {exc.code}") from exc
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"download da origem falhou: {exc}") from exc
    if len(payload) > MAX_BYTES:
        raise UsageError("arquivo acima do limite de 200 MiB")
    return content_type, payload


def download_source(url: str, *, fetch: Callable[[str], tuple[str, bytes]] | None = None) -> bytes:
    source = validate_source_url(canonical_source_url(url))
    getter = fetch or fetch_source_bytes
    content_type, payload = getter(source)
    path = urlparse(source).path.lower()
    if _is_html(content_type, payload) and not path.endswith((".html", ".htm")):
        raise UsageError("a origem devolveu HTML, não o arquivo")
    if not payload or len(payload) > MAX_BYTES:
        raise UsageError("arquivo de origem vazio ou acima do limite de 200 MiB")
    return payload


def upload_public_file(folder_id: str, filename: str, payload: bytes, *, token: str | None = None, timeout: float = 60) -> str:
    if token is None:
        token = drive_access_token()
    boundary = f"iaorchestrator{sha256_bytes(payload)[:16]}"
    metadata = json.dumps({"name": safe_filename(filename), "parents": [folder_id]}).encode("utf-8")
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
            metadata,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            payload,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise UsageError(
                "o Drive recusou a escrita na pasta pública; defina IA_ORCHESTRATOR_DRIVE_TOKEN "
                "ou grave o access token em ~/.ia_orchestrator/drive_token"
            ) from exc
        raise UsageError(f"envio ao Drive falhou com HTTP {exc.code}") from exc
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"envio ao Drive falhou: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise UsageError("resposta do Drive inválida") from exc
    file_id = str(data.get("id") or "")
    if not _DRIVE_ID.fullmatch(file_id):
        raise UsageError("resposta do Drive sem id")
    return file_id


def delete_drive_file(file_id: str, *, token: str | None = None, timeout: float = 60) -> None:
    if not _DRIVE_ID.fullmatch(file_id):
        raise UsageError("id do Drive inválido")
    if token is None:
        token = drive_access_token()
    if not token:
        raise UsageError("apagar no Drive exige IA_ORCHESTRATOR_DRIVE_TOKEN ou ~/.ia_orchestrator/drive_token")
    request = urllib.request.Request(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise UsageError(f"apagar no Drive falhou com HTTP {exc.code}") from exc
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"apagar no Drive falhou: {exc}") from exc


def stage_public_upload(
    spec: dict[str, Any],
    *,
    fetch: Callable[[str], tuple[str, bytes]] | None = None,
    upload: Callable[..., str] = upload_public_file,
    token: str | None = None,
    workspace: Path | None = None,
    repository: str | None = None,
    read_git: Callable[..., bytes | None] = read_project_git_file,
) -> dict[str, Any]:
    filename = spec["filename"]
    try:
        payload = None
        source_protocol = "https"
        if workspace is not None and repository:
            payload = read_git(spec["source_url"], workspace=workspace, repository=repository)
            if payload is not None:
                source_protocol = "git"
        if payload is None:
            payload = download_source(spec["source_url"], fetch=fetch)
        digest = sha256_bytes(payload)
        size = len(payload)
        if spec.get("sha256") and digest != spec["sha256"]:
            raise UsageError("tamanho ou hash não confere")
        if spec.get("bytes") is not None and size != int(spec["bytes"]):
            raise UsageError("tamanho ou hash não confere")
        with tempfile.TemporaryDirectory(prefix="ia-orchestrator-get-file-") as directory:
            path = Path(directory) / filename
            path.write_bytes(payload)
            reread, reread_size = sha256_file(path)
            if reread != digest or reread_size != size:
                raise UsageError("releitura do arquivo temporário não confere")
            file_id = upload(spec["folder_id"], filename, path.read_bytes(), token=token)
    except UsageError as exc:
        return {"status": "failed", "error": str(exc), "filename": filename, "delete_from_drive": False}
    return {
        "status": "success",
        "filename": filename,
        "sha256": digest,
        "bytes": size,
        "drive_url": canonical_file_url(file_id),
        "file_id": file_id,
        "folder_url": spec["folder_url"],
        "source_protocol": source_protocol,
        "delete_from_drive": True,
    }


def incoming_path(cfg: Any, home: Path | None, filename: str) -> Path:
    return data_dir(cfg, home) / "get_file" / "incoming" / safe_filename(filename)


def collect_received_file(
    result: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
    fetch: Callable[[str], bytes] = download_public_file,
    delete: Callable[[str], None] = delete_drive_file,
) -> dict[str, Any]:
    if result.get("status") != "success":
        return {"status": "failed", "error": result.get("error") or "get_file sem sucesso", "deleted": False}
    destination = output.expanduser().resolve()
    if destination.exists() and not overwrite:
        return {"status": "failed", "error": "arquivo local já existe", "path": str(destination), "deleted": False}
    try:
        payload = fetch(str(result["file_id"]))
    except UsageError as exc:
        return {"status": "failed", "error": str(exc), "deleted": False}
    if len(payload) != int(result["bytes"]) or sha256_bytes(payload) != result["sha256"]:
        return {"status": "failed", "error": "tamanho ou hash não confere", "deleted": False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    try:
        partial.write_bytes(payload)
        if sha256_file(partial)[0] != result["sha256"]:
            raise UsageError("releitura do arquivo recebido não confere")
        os.replace(partial, destination)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        return {"status": "failed", "error": str(exc) or "falha ao gravar", "deleted": False}
    deleted = False
    delete_error = None
    try:
        delete(str(result["file_id"]))
        deleted = True
    except UsageError as exc:
        delete_error = str(exc)
    collected = {
        "status": "success",
        "path": str(destination),
        "filename": result["filename"],
        "sha256": result["sha256"],
        "bytes": result["bytes"],
        "deleted": deleted,
    }
    if delete_error:
        collected["delete_error"] = delete_error
    return collected


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


def perform_executor_get_file(engine: Any, home: Path | None, env: Any, body: str) -> dict[str, Any]:
    cfg = engine.cfg
    task = engine.store.get_task(cfg.namespace, env.task_id)
    if task is None:
        raise UsageError("tarefa não encontrada")
    if _other_running(cfg, home, str(env.request_id)):
        outcome = {"status": "failed", "error": "executor ocupado com outro job", "delete_from_drive": False}
        _deliver(engine, task, env, outcome)
        return outcome
    try:
        spec = parse_request(body)
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
    outcome = stage_public_upload(
        spec,
        workspace=cfg.workspace_root(),
        repository=str(cfg.github.repository),
    )
    _deliver(engine, task, env, outcome)
    return outcome


def publish_orchestrator_get_file(engine: Any, task: dict[str, Any], spec: dict[str, Any]) -> Any:
    if _issue_busy(engine, task):
        raise UsageError("get-file espera a executora IDLE; a issue tem execução activa")
    request_id = new_id()
    env = engine._publish(
        task,
        MessageType.GET_FILE.value,
        render_get_file_body(spec),
        recipient="executor",
        request_id=request_id,
    )
    engine.flush_outbox()
    return env
