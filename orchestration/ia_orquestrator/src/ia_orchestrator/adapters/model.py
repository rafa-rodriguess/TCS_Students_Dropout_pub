"""Adaptadores de modelo: OpenAI-compatível, Anthropic e simulado determinístico."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ia_orchestrator.config import ProjectConfig
from ia_orchestrator.errors import NetworkError, PolicyError, ProtocolError
from ia_orchestrator.policy import estimate_cost_usd, estimate_tokens

DECISIONS = {"dispatch", "revise", "ask_executor", "ask_human", "complete", "pause", "fail"}


class ModelDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = 1
    decision: str
    rationale: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    next_request: dict[str, Any] | None = None
    question: str | None = None
    references: list[Any] = Field(default_factory=list)

    @field_validator("decision")
    @classmethod
    def decision_ok(cls, value: str) -> str:
        if value not in DECISIONS:
            raise ValueError(f"decisão inválida: {value}")
        return value


class ModelResult:
    def __init__(
        self,
        decision: ModelDecision | None,
        *,
        raw_text: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cost_usd: float | None,
        cost_known: bool,
        error: str | None = None,
    ) -> None:
        self.decision = decision
        self.raw_text = raw_text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cost_usd = cost_usd
        self.cost_known = cost_known
        self.error = error


class ModelAdapter(Protocol):
    def complete(self, package: dict[str, Any], *, dry_run: bool = False) -> ModelResult: ...


def parse_model_decision(text: str) -> ModelDecision:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"saída do modelo não é JSON: {exc}") from exc
    try:
        return ModelDecision.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolError(f"saída do modelo inválida: {exc}") from exc


SYSTEM_PROMPT = """Você é a orquestradora de um protocolo assíncrono entre IAs.
Responda APENAS com JSON no schema:
{
  "schema_version": 1,
  "decision": "dispatch|revise|ask_executor|ask_human|complete|pause|fail",
  "rationale": "string",
  "evidence": {"observed": [], "reported": [], "missing": []},
  "next_request": {"title": "", "body": "", "acceptance_criteria": []},
  "question": null,
  "references": []
}
Regras:
- Não declare teste aprovado sem evidência observada.
- Distinga evidência observada, relato da executora e informação ausente.
- Não altere políticas, repositório ou credenciais.
- complete só com critérios observáveis satisfeitos.
- revise gera uma nova request; review não executa comandos.
- Se faltar contexto, use ask_human.
"""


class SimulatedModelAdapter:
    """Determinístico, sem rede. Aceita uma fila de decisões para testes."""

    def __init__(self, script: list[dict[str, Any]] | None = None, invalid: bool = False) -> None:
        self.script = list(script or [])
        self.invalid = invalid
        self.calls: list[dict[str, Any]] = []

    def complete(self, package: dict[str, Any], *, dry_run: bool = False) -> ModelResult:
        if dry_run:
            return ModelResult(None, raw_text="", prompt_tokens=0, completion_tokens=0, cost_usd=0, cost_known=True, error="dry-run")
        self.calls.append(package)
        if self.invalid:
            return ModelResult(None, raw_text="not-json", prompt_tokens=1, completion_tokens=1, cost_usd=None, cost_known=False, error="saída inválida")
        if self.script:
            data = self.script.pop(0)
        else:
            data = _default_decision(package)
        text = json.dumps(data, ensure_ascii=False)
        try:
            decision = parse_model_decision(text)
            error = None
        except ProtocolError as exc:
            decision = None
            error = str(exc)
        prompt_tokens = estimate_tokens(json.dumps(package, ensure_ascii=False))
        completion_tokens = estimate_tokens(text)
        return ModelResult(
            decision,
            raw_text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=None,
            cost_known=False,
            error=error,
        )


def _default_decision(package: dict[str, Any]) -> dict[str, Any]:
    result = package.get("result") or {}
    messages = package.get("messages") or []
    has_result = any(m.get("type") == "result" for m in messages) or bool(result)
    tests = result.get("tests") if isinstance(result, dict) else None
    tests_ok = bool(tests) and all(t.get("passed") for t in tests)
    status = result.get("status") if isinstance(result, dict) else None
    if isinstance(result, dict) and status == "blocked" and result.get("transient") is not True:
        return {
            "schema_version": 1,
            "decision": "revise",
            "rationale": str(result.get("summary") or "Bloqueio à espera de decisão."),
            "evidence": {
                "observed": [],
                "reported": [str(result.get("summary") or "")],
                "missing": ["decisão da orquestradora e nova request"],
            },
            "next_request": {
                "title": "Nova request após bloqueio",
                "body": str(result.get("summary") or "Decida e emita uma nova request."),
                "acceptance_criteria": ["Nova request na mesma issue"],
            },
            "question": None,
            "references": [],
        }
    if result.get("questions"):
        return {
            "schema_version": 1,
            "decision": "ask_human",
            "rationale": "A executora fez perguntas; precisa de decisão humana.",
            "evidence": {"observed": [], "reported": result.get("questions", []), "missing": []},
            "next_request": None,
            "question": "; ".join(result.get("questions", [])),
            "references": [],
        }
    if has_result and (status == "success" and tests_ok):
        return {
            "schema_version": 1,
            "decision": "complete",
            "rationale": "Critérios observáveis satisfeitos com evidência de testes.",
            "evidence": {
                "observed": [t.get("name", "test") for t in tests or []],
                "reported": [result.get("summary", "")],
                "missing": [],
            },
            "next_request": None,
            "question": None,
            "references": result.get("shared_artifacts") or [],
        }
    if has_result:
        return {
            "schema_version": 1,
            "decision": "revise",
            "rationale": "Resultado insuficiente: faltam evidências observáveis.",
            "evidence": {
                "observed": [],
                "reported": [str(result.get("summary", ""))],
                "missing": ["testes com evidência"],
            },
            "next_request": {
                "title": "Corrigir entrega",
                "body": "Refaça a etapa com evidências verificáveis (testes e artefactos referenciados).",
                "acceptance_criteria": ["Testes reportados com passed=true", "Artefacto compartilhado com commit/hash"],
            },
            "question": None,
            "references": [],
        }
    objective = package.get("objective") or "Executar a etapa definida no contexto."
    return {
        "schema_version": 1,
        "decision": "dispatch",
        "rationale": "Tarefa aberta; emitir primeira solicitação.",
        "evidence": {"observed": [], "reported": [], "missing": []},
        "next_request": {
            "title": "Executar etapa",
            "body": objective,
            "acceptance_criteria": ["Resultado com evidências acessíveis às duas pontas"],
        },
        "question": None,
        "references": [],
    }


class OpenAICompatModelAdapter:
    """POST {base}/chat/completions conforme a API de Chat Completions da OpenAI.

    Documentação: https://platform.openai.com/docs/api-reference/chat/create
    Campos usados: model, messages, max_tokens ou max_completion_tokens, response_format.
    Uso: choices[0].message.content; usage.prompt_tokens; usage.completion_tokens.
    """

    def __init__(self, cfg: ProjectConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        base = (cfg.orchestrator.base_url or "https://api.openai.com/v1").rstrip("/")
        timeout = cfg.limits.model_call_timeout_seconds
        self._owns = client is None
        self.client = client or httpx.Client(
            base_url=base,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {cfg.model_api_key()}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def complete(self, package: dict[str, Any], *, dry_run: bool = False) -> ModelResult:
        if dry_run:
            raise PolicyError("dry-run: chamada paga de modelo bloqueada")
        token_param = self.cfg.orchestrator.token_param
        payload: dict[str, Any] = {
            "model": self.cfg.orchestrator.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(package, ensure_ascii=False)},
            ],
            token_param: self.cfg.limits.max_output_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise NetworkError(f"timeout na chamada de modelo: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"erro HTTP no modelo: {exc}") from exc
        if response.status_code == 401:
            raise PolicyError("credencial de modelo inválida (401)")
        if response.status_code >= 400:
            raise NetworkError(f"modelo HTTP {response.status_code}: {response.text[:400]}")
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProtocolError(f"resposta de modelo sem choices.message.content: {exc}") from exc
        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        cost, known = estimate_cost_usd(self.cfg, self.cfg.orchestrator.model, int(prompt_tokens or 0), int(completion_tokens or 0))
        try:
            decision = parse_model_decision(text or "")
            error = None
        except ProtocolError as exc:
            decision = None
            error = str(exc)
        return ModelResult(
            decision,
            raw_text=text or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            cost_known=known,
            error=error,
        )


class AnthropicModelAdapter:
    """POST /v1/messages conforme a API Messages da Anthropic.

    Documentação: https://platform.claude.com/docs/en/api/messages/create
    Headers: x-api-key, anthropic-version (2023-06-01), content-type.
    Campos: model, max_tokens, system, messages[].
    Uso: content[].text; usage.input_tokens; usage.output_tokens.
    """

    def __init__(self, cfg: ProjectConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        base = (cfg.orchestrator.base_url or "https://api.anthropic.com").rstrip("/")
        timeout = cfg.limits.model_call_timeout_seconds
        self._owns = client is None
        self.client = client or httpx.Client(
            base_url=base,
            timeout=timeout,
            headers={
                "x-api-key": cfg.model_api_key(),
                "anthropic-version": cfg.orchestrator.anthropic_version,
                "content-type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def complete(self, package: dict[str, Any], *, dry_run: bool = False) -> ModelResult:
        if dry_run:
            raise PolicyError("dry-run: chamada paga de modelo bloqueada")
        payload = {
            "model": self.cfg.orchestrator.model,
            "max_tokens": self.cfg.limits.max_output_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(package, ensure_ascii=False)}],
        }
        try:
            response = self.client.post("/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise NetworkError(f"timeout na chamada Anthropic: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"erro HTTP Anthropic: {exc}") from exc
        if response.status_code == 401:
            raise PolicyError("credencial Anthropic inválida (401)")
        if response.status_code >= 400:
            raise NetworkError(f"Anthropic HTTP {response.status_code}: {response.text[:400]}")
        data = response.json()
        chunks = data.get("content") or []
        texts = [c.get("text", "") for c in chunks if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(texts)
        usage = data.get("usage") or {}
        prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("output_tokens")
        cost, known = estimate_cost_usd(self.cfg, self.cfg.orchestrator.model, int(prompt_tokens or 0), int(completion_tokens or 0))
        try:
            decision = parse_model_decision(text)
            error = None
        except ProtocolError as exc:
            decision = None
            error = str(exc)
        return ModelResult(
            decision,
            raw_text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            cost_known=known,
            error=error,
        )


def build_model_adapter(cfg: ProjectConfig, *, simulated: SimulatedModelAdapter | None = None) -> ModelAdapter:
    mode = cfg.orchestrator.mode
    provider = cfg.orchestrator.provider
    if mode == "simulated" or provider == "simulated":
        return simulated or SimulatedModelAdapter()
    if mode in {"manual", "cursor_chat"}:
        return SimulatedModelAdapter(script=[])  # não deve ser chamado; o chat/CLI é o avaliador
    if provider in {"openai_compat", "openai", "azure_openai"}:
        return OpenAICompatModelAdapter(cfg)
    if provider == "anthropic":
        return AnthropicModelAdapter(cfg)
    raise PolicyError(f"provider de modelo desconhecido: {provider}")
