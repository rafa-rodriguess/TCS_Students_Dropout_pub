"""Adaptador de execução por processo externo e simulado."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ia_orchestrator.errors import PolicyError
from ia_orchestrator.policy import subprocess_env
from ia_orchestrator.state import ExecutionState


class ExecutorInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_id: str
    repository: str
    task_id: str
    request_id: str
    attempt: int
    prompt: str
    context: dict[str, Any]
    context_revision: str | None = None
    cwd: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class SharedArtifact(BaseModel):
    model_config = ConfigDict(extra="allow")
    repository: str | None = None
    path: str
    commit: str | None = None
    sha256: str | None = None


class TestResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    passed: bool
    evidence: str | None = None


class ExecutorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    summary: str = ""
    files_modified: list[str] = Field(default_factory=list)
    shared_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None


class ExecutorAdapter(Protocol):
    def run(self, payload: ExecutorInput, *, dry_run: bool = False) -> ExecutorOutput: ...


def parse_executor_output(text: str) -> ExecutorOutput:
    raw = text.strip()
    if not raw:
        raise PolicyError("stdout do executor vazio")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"stdout do executor não é JSON: {exc}") from exc
    out = ExecutorOutput.model_validate(data)
    if out.status not in {"success", "blocked", "failed", "unknown"}:
        raise PolicyError(f"status de executor inválido: {out.status}")
    return out


class SimulatedExecutorAdapter:
    def __init__(self, script: list[dict[str, Any]] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[ExecutorInput] = []
        self.killed = False

    def run(self, payload: ExecutorInput, *, dry_run: bool = False) -> ExecutorOutput:
        if dry_run:
            raise PolicyError("dry-run: subprocesso de trabalho bloqueado")
        self.calls.append(payload)
        if self.script:
            return ExecutorOutput.model_validate(self.script.pop(0))
        prompt = payload.prompt.lower()
        if "crash-unknown" in prompt:
            return ExecutorOutput(status="unknown", summary="execução em estado desconhecido", checkpoint={"note": "consultar operador"})
        if "bloquear" in prompt or "block" in prompt:
            return ExecutorOutput(status="blocked", summary="precisa de esclarecimento", questions=["Qual branch usar?"])
        if "falhar" in prompt or "fail" in prompt:
            return ExecutorOutput(status="failed", summary="falha recuperável", errors=["comando X saiu 1"])
        if payload.attempt == 1 and "insuficiente" not in prompt:
            # primeira tentativa sem evidência completa
            return ExecutorOutput(
                status="success",
                summary="Rascunho sem testes.",
                files_modified=["README.md"],
                tests=[],
                shared_artifacts=[],
            )
        return ExecutorOutput(
            status="success",
            summary="Entrega com testes.",
            files_modified=["README.md"],
            tests=[{"name": "demo", "passed": True, "evidence": "log://demo"}],
            shared_artifacts=[{"repository": payload.repository, "path": "docs/demo.md", "commit": "deadbeef", "sha256": "abc"}],
        )


class SubprocessExecutorAdapter:
    """Comando como lista de argumentos, JSON em stdin/stdout, sem shell=True."""

    def __init__(self, command: list[str], cwd: Path, timeout: int) -> None:
        if not command:
            raise PolicyError("executor.command vazio; configure a lista de argumentos ou use mode=simulated/manual")
        self.command = list(command)
        self.cwd = cwd
        self.timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None

    def interrupt(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self, payload: ExecutorInput, *, dry_run: bool = False) -> ExecutorOutput:
        if dry_run:
            raise PolicyError("dry-run: subprocesso de trabalho bloqueado")
        data = payload.model_dump()
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 — lista de args, sem shell
                self.command,
                input=encoded,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.cwd),
                timeout=self.timeout,
                env=subprocess_env(),
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutorOutput(status="unknown", summary="timeout do subprocesso", errors=["timeout"], checkpoint={"status": ExecutionState.UNKNOWN.value})
        stderr = completed.stderr.decode("utf-8", errors="replace")
        stdout = completed.stdout.decode("utf-8", errors="replace")
        if completed.returncode != 0 and not stdout.strip():
            return ExecutorOutput(
                status="failed",
                summary=f"executor saiu {completed.returncode}",
                errors=[stderr[-2000:]],
            )
        try:
            return parse_executor_output(stdout)
        except PolicyError:
            if completed.returncode != 0:
                return ExecutorOutput(status="failed", summary="saída inválida", errors=[stdout[-1000:], stderr[-1000:]])
            return ExecutorOutput(status="unknown", summary="stdout não parseável após exit 0", errors=[stdout[-1000:]], checkpoint={"stderr": stderr[-1000:]})
