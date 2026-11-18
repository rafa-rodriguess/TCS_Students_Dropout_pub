"""Envelope versionado, canonicalização, tipos e parsing de mensagens."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ia_orchestrator import PROTOCOL_VERSION as PACKAGE_PROTOCOL_VERSION, UTIL_VERSION
from ia_orchestrator.errors import ProtocolError

PROTOCOL_VERSION = PACKAGE_PROTOCOL_VERSION
MARKER_START = "<!-- ia-orchestrator:message:v1 -->"
MARKER_START_PREFIX = "<!-- ia-orchestrator:message:v"
MARKER_BODY = "<!-- ia-orchestrator:body -->"
MARKER_END = "<!-- ia-orchestrator:end -->"
QUARANTINE_NOTICE_MARKER = "<!-- ia-orchestrator:quarantine-notice -->"
EXECUTOR_CAPABILITIES_PREFIX = "<!-- ia-orchestrator:executor-capabilities:v1 "
MAX_BODY_BYTES = 65536
MAX_ENVELOPE_BYTES = 16384
ROLES = ("human", "orchestrator", "executor", "agent")
RECIPIENTS = (*ROLES, "broadcast")


class MessageType(str, Enum):
    DISCUSS = "discuss"
    ANALYSIS = "analysis"
    TASK_OPEN = "task_open"
    REQUEST = "request"
    NON_BLOCKING = "non_blocking"
    PROGRAMMED_STOP = "programmed_stop"
    ACK = "ack"
    PROGRESS = "progress"
    QUESTION = "question"
    ANSWER = "answer"
    RESULT = "result"
    CONTROL_RESULT = "control_result"
    REVIEW = "review"
    ERROR = "error"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    COMPLETE = "complete"
    SEND_FILE = "send_file"
    SEND_FILE_READY = "send_file_ready"
    GET_FILE = "get_file"


EXECUTABLE_TYPES = {item.value for item in MessageType}
RECOVERY_CONTROL_TYPES = {
    MessageType.NON_BLOCKING.value,
    MessageType.PROGRAMMED_STOP.value,
}
CONTROL_RESULT_TYPES = {MessageType.CONTROL_RESULT.value}
CONTROL_TYPES = {
    MessageType.PAUSE.value,
    MessageType.RESUME.value,
    MessageType.CANCEL.value,
    MessageType.COMPLETE.value,
}
NO_MODEL_TYPES = {
    MessageType.DISCUSS.value,
    MessageType.ANALYSIS.value,
    MessageType.ACK.value,
    MessageType.PROGRESS.value,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def executor_capabilities_payload() -> dict[str, Any]:
    return {
        "util_version": UTIL_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "message_types": [
            MessageType.NON_BLOCKING.value,
            MessageType.PROGRAMMED_STOP.value,
            MessageType.CONTROL_RESULT.value,
        ],
        "features": ["send_file", "get_file"],
    }


def render_executor_capabilities() -> str:
    return (
        EXECUTOR_CAPABILITIES_PREFIX
        + json.dumps(executor_capabilities_payload(), sort_keys=True, separators=(",", ":"))
        + " -->"
    )


STATUS_TELEMETRY_HEADING = "## STATUS — telemetria não bloqueante"


def status_telemetry_body() -> str:
    """Corpo fixo do non_blocking publicado por `ia-orchestrator status`."""
    return (
        f"{STATUS_TELEMETRY_HEADING}\n"
        "\n"
        "Pedido de observabilidade da execução primária activa. Não pare, não reinicie e não altere o run.\n"
        "\n"
        "Responda com control_result assim que a leitura terminar. Se a leitura interferir de forma material, use status blocked.\n"
        "\n"
        "Reporte só o que estiver disponível sem prejudicar o job:\n"
        "- processo vivo ou não\n"
        "- unidade em processamento\n"
        "- concluído / total, se for mensurável\n"
        "- checkpoint mais recente\n"
        "- artefactos completos e parciais\n"
        "- warnings e erros\n"
        "- CPU e RAM, se a leitura for barata\n"
        "- confirmação de que a metodologia não mudou\n"
    )


def parse_executor_capabilities(body: str | None) -> dict[str, Any] | None:
    text = canonicalize_body(body or "")
    start = text.find(EXECUTOR_CAPABILITIES_PREFIX)
    if start < 0:
        return None
    start += len(EXECUTOR_CAPABILITIES_PREFIX)
    end = text.find(" -->", start)
    if end < 0:
        return None
    try:
        payload = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def canonicalize_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n")


def canonical_payload(body: str) -> str:
    return canonicalize_body(body).strip("\n")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def routing_namespace(host: str, repository: str, project_id: str) -> str:
    return f"{host.lower()}|{repository.lower()}|{project_id}"


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=PROTOCOL_VERSION)
    project_id: str
    repository: str
    task_id: str
    message_id: str
    sender_role: str
    sender_id: str
    recipient_role: str
    type: str
    in_reply_to: str | None = None
    request_id: str | None = None
    attempt: int = 1
    created_at: str
    context_revision: str | None = None
    payload_sha256: str

    @field_validator("schema_version")
    @classmethod
    def version_ok(cls, value: int) -> int:
        if value != PROTOCOL_VERSION:
            raise ValueError(f"schema_version incompatível: {value}")
        return value

    @field_validator("repository")
    @classmethod
    def repo_ok(cls, value: str) -> str:
        if value.count("/") != 1 or not all(value.split("/")):
            raise ValueError("repository deve ser owner/repo")
        return value

    @field_validator("sender_role")
    @classmethod
    def sender_ok(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError(f"sender_role inválido: {value}")
        return value

    @field_validator("recipient_role")
    @classmethod
    def recipient_ok(cls, value: str) -> str:
        if value not in RECIPIENTS:
            raise ValueError(f"recipient_role inválido: {value}")
        return value

    @field_validator("type")
    @classmethod
    def type_ok(cls, value: str) -> str:
        if value not in EXECUTABLE_TYPES:
            raise ValueError(f"tipo inválido: {value}")
        return value

    @field_validator("attempt")
    @classmethod
    def attempt_ok(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempt deve ser >= 1")
        return value

    def required_fields_for_type(self) -> None:
        needs_request = self.type in {
            MessageType.REQUEST.value,
            MessageType.DISCUSS.value,
            MessageType.ANALYSIS.value,
            MessageType.NON_BLOCKING.value,
            MessageType.PROGRAMMED_STOP.value,
            MessageType.CONTROL_RESULT.value,
            MessageType.ACK.value,
            MessageType.PROGRESS.value,
            MessageType.RESULT.value,
            MessageType.REVIEW.value,
            MessageType.ANSWER.value,
            MessageType.SEND_FILE.value,
            MessageType.SEND_FILE_READY.value,
            MessageType.GET_FILE.value,
        }
        if needs_request and not self.request_id:
            raise ProtocolError(f"{self.type} exige request_id")
        if self.type == MessageType.DISCUSS.value:
            if self.sender_role != "orchestrator" or self.recipient_role != "agent":
                raise ProtocolError("discuss exige orchestrator → agent")
            if self.in_reply_to is not None:
                raise ProtocolError("discuss é pedido novo, sem in_reply_to")
        elif self.type == MessageType.ANALYSIS.value:
            if self.sender_role != "agent" or self.recipient_role != "orchestrator":
                raise ProtocolError("analysis exige agent → orchestrator")
        elif self.sender_role == "agent" and not (
            self.type == MessageType.QUESTION.value and self.recipient_role == "orchestrator"
        ):
            raise ProtocolError("agent só pode emitir analysis/question para orchestrator")
        elif self.recipient_role == "agent":
            raise ProtocolError("agent só recebe discuss")
        if self.sender_role == "agent" and (not self.request_id or not self.in_reply_to):
            raise ProtocolError("agent exige discuss request_id e in_reply_to")
        if self.type == MessageType.SEND_FILE.value and (
            self.sender_role != "orchestrator" or self.recipient_role != "executor"
        ):
            raise ProtocolError("send_file exige orchestrator → executor")
        if self.type == MessageType.GET_FILE.value and (
            self.sender_role != "orchestrator" or self.recipient_role != "executor"
        ):
            raise ProtocolError("get_file exige orchestrator → executor")
        if self.type == MessageType.SEND_FILE_READY.value and (
            self.sender_role != "executor" or self.recipient_role != "orchestrator"
        ):
            raise ProtocolError("send_file_ready exige executor → orchestrator")
        if self.type == MessageType.TASK_OPEN.value and self.in_reply_to is not None:
            raise ProtocolError("task_open não deve referenciar in_reply_to")
        if self.type in {
            MessageType.ANALYSIS.value,
            MessageType.ACK.value,
            MessageType.ANSWER.value,
            MessageType.RESULT.value,
            MessageType.CONTROL_RESULT.value,
            MessageType.SEND_FILE_READY.value,
        } and not self.in_reply_to:
            raise ProtocolError(f"{self.type} exige in_reply_to")


class ParsedComment:
    def __init__(
        self,
        *,
        kind: str,
        envelope: Envelope | None = None,
        body: str = "",
        raw: str = "",
        error: str | None = None,
        incompatible: bool = False,
    ) -> None:
        self.kind = kind  # envelope, observation, quarantine
        self.envelope = envelope
        self.body = body
        self.raw = raw
        self.error = error
        self.incompatible = incompatible


_VERSION_RE = re.compile(r"<!-- ia-orchestrator:message:v(\d+) -->")


def parse_comment(raw: str) -> ParsedComment:
    text = canonicalize_body(raw or "")
    if QUARANTINE_NOTICE_MARKER in text:
        return ParsedComment(kind="observation", body=text, raw=text)
    if MARKER_START_PREFIX not in text:
        return ParsedComment(kind="observation", body=text, raw=text)
    match = _VERSION_RE.search(text)
    if not match:
        return ParsedComment(kind="quarantine", raw=text, error="marcador de versão irreconhecível")
    version = int(match.group(1))
    if version != PROTOCOL_VERSION:
        return ParsedComment(
            kind="quarantine",
            raw=text,
            error=f"versão de protocolo incompatível: v{version}",
            incompatible=True,
        )
    if MARKER_START not in text or MARKER_BODY not in text or MARKER_END not in text:
        return ParsedComment(kind="quarantine", raw=text, error="marcadores de envelope incompletos")
    try:
        pre, rest = text.split(MARKER_START, 1)
        json_part, rest = rest.split(MARKER_BODY, 1)
        body, _tail = rest.split(MARKER_END, 1)
    except ValueError:
        return ParsedComment(kind="quarantine", raw=text, error="falha ao fatiar envelope")
    json_part = json_part.strip()
    if json_part.startswith("```json"):
        json_part = json_part[len("```json") :].strip()
    if json_part.startswith("```"):
        json_part = json_part[3:].strip()
    if json_part.endswith("```"):
        json_part = json_part[:-3].strip()
    if len(json_part.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        return ParsedComment(kind="quarantine", raw=text, error="envelope excede o limite de tamanho")
    body = body.strip("\n")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        return ParsedComment(kind="quarantine", raw=text, error="corpo excede o limite de tamanho")
    try:
        data = json.loads(json_part)
        envelope = Envelope.model_validate(data)
        envelope.required_fields_for_type()
    except Exception as exc:  # noqa: BLE001 — diagnóstico de quarentena
        return ParsedComment(kind="quarantine", raw=text, error=f"envelope inválido: {exc}")
    expected = sha256_text(canonical_payload(body))
    if envelope.payload_sha256 != expected:
        return ParsedComment(
            kind="quarantine",
            envelope=envelope,
            body=body,
            raw=text,
            error=(
                "payload_sha256 não coincide com o corpo canonicalizado "
                f"(envelope={envelope.payload_sha256}, corpo={expected})"
            ),
        )
    return ParsedComment(kind="envelope", envelope=envelope, body=body, raw=text)


def format_quarantine_notice(
    *,
    reason: str,
    role: str,
    github_comment_id: int | None = None,
    message_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Comentário visível na issue: diagnóstico, não é envelope executável."""
    cid = "none" if github_comment_id is None else str(int(github_comment_id))
    mid = message_id or "none"
    pid = project_id or "unknown"
    return (
        f"{QUARANTINE_NOTICE_MARKER}\n"
        f"<!-- source-comment-id: {cid} -->\n"
        f"<!-- source-message-id: {mid} -->\n"
        "## Quarentena (não executável)\n\n"
        "Este comentário **não** foi aceite como mensagem do protocolo. "
        "Não execute o envelope original e não trate este aviso como `request`.\n\n"
        f"- **Motivo:** {reason}\n"
        f"- **Detectado por:** `{role}`\n"
        f"- **project_id:** `{pid}`\n"
        f"- **comentário GitHub origem:** `{cid}`\n"
        f"- **message_id:** `{mid}`\n\n"
        "Corrija o envelope (por exemplo `payload_sha256` = SHA-256 do corpo entre "
        "`<!-- ia-orchestrator:body -->` e `<!-- ia-orchestrator:end -->`, sem os marcadores) "
        "e publique **um comentário novo**. Editar o comentário recusado não o reativa.\n"
    )


def quarantine_notice_matches(
    body: str,
    *,
    github_comment_id: int | None = None,
    message_id: str | None = None,
) -> bool:
    text = canonicalize_body(body or "")
    if QUARANTINE_NOTICE_MARKER not in text:
        return False
    if github_comment_id is not None and f"source-comment-id: {int(github_comment_id)}" in text:
        return True
    if message_id and f"source-message-id: {message_id}" in text:
        return True
    return False


def render_message(envelope: Envelope, body: str) -> str:
    body = canonical_payload(body)
    payload = envelope.model_copy(update={"payload_sha256": sha256_text(body)})
    payload.required_fields_for_type()
    json_block = json.dumps(payload.model_dump(), indent=2, ensure_ascii=False)
    rendered = (
        f"{MARKER_START}\n"
        f"```json\n{json_block}\n```\n"
        f"{MARKER_BODY}\n"
        f"{body.rstrip()}\n"
        f"{MARKER_END}\n"
    )
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ProtocolError("corpo excede o limite de tamanho")
    return rendered


def build_envelope(
    *,
    project_id: str,
    repository: str,
    task_id: str,
    sender_role: str,
    sender_id: str,
    recipient_role: str,
    type: str,
    body: str,
    in_reply_to: str | None = None,
    request_id: str | None = None,
    attempt: int = 1,
    context_revision: str | None = None,
    message_id: str | None = None,
    created_at: str | None = None,
) -> Envelope:
    canonical = canonical_payload(body)
    return Envelope(
        schema_version=PROTOCOL_VERSION,
        project_id=project_id,
        repository=repository,
        task_id=task_id,
        message_id=message_id or new_id(),
        sender_role=sender_role,
        sender_id=sender_id,
        recipient_role=recipient_role,
        type=type,
        in_reply_to=in_reply_to,
        request_id=request_id,
        attempt=attempt,
        created_at=created_at or utc_now(),
        context_revision=context_revision,
        payload_sha256=sha256_text(canonical),
    )


def comment_hash(raw: str) -> str:
    return sha256_text(canonicalize_body(raw))
