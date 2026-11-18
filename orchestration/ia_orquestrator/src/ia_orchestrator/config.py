"""Configuração multi-projecto, isolamento e validação."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ia_orchestrator.errors import PolicyError, UsageError
from ia_orchestrator.protocol import routing_namespace


def default_home() -> Path:
    raw = os.environ.get("IA_ORCHESTRATOR_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home().expanduser().resolve() / ".ia_orchestrator"


class AllowedSenders(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human: list[str] = Field(default_factory=list)
    orchestrator: list[str] = Field(default_factory=list)
    executor: list[str] = Field(default_factory=list)
    agent: list[str] = Field(default_factory=list)

    def logins_for(self, role: str) -> list[str]:
        return list(getattr(self, role, []))

    def all_logins(self) -> set[str]:
        return set(self.human + self.orchestrator + self.executor + self.agent)


class GitHubSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "github.com"
    repository: str
    token_env: str
    allowed_senders: AllowedSenders
    api_base: str | None = None

    @field_validator("repository")
    @classmethod
    def repo_ok(cls, value: str) -> str:
        parts = value.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("github.repository deve ser owner/repo")
        return value

    def owner_repo(self) -> tuple[str, str]:
        owner, repo = self.repository.split("/", 1)
        return owner, repo

    def resolved_api_base(self) -> str:
        if self.api_base:
            return self.api_base.rstrip("/")
        if self.host.lower() in {"github.com", "api.github.com"}:
            return "https://api.github.com"
        return f"https://{self.host}/api/v3"


class ArtifactsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str | None = None


class WorkspaceSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: str


class ContextSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: str | None = None
    source_of_truth: str | None = None
    instructions: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class PricingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_per_1m: float
    output_per_1m: float


class PricingSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str = "usd"
    models: dict[str, PricingModel] = Field(default_factory=dict)


class OrchestratorSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "api"  # api | manual | simulated | cursor_chat
    provider: str = "openai_compat"  # openai_compat | anthropic | simulated
    model: str = "modelo-configurado"
    api_key_env: str | None = None
    base_url: str | None = None
    worker_id: str = "orchestrator-01"
    owner: str | None = None
    token_param: str = "max_tokens"  # max_tokens | max_completion_tokens
    anthropic_version: str = "2023-06-01"


class ExecutorSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "subprocess"  # subprocess | manual | simulated | cursor_chat
    command: list[str] = Field(default_factory=list)
    worker_id: str = "executor-01"
    owner: str | None = None
    timeout_seconds: int | None = None

    @field_validator("command")
    @classmethod
    def command_is_list(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item for item in value):
            raise ValueError("executor.command deve ser lista de argumentos não vazios")
        return value


class AgentSection(BaseModel):
    """Discussion-only role; it has no executor adapter or code-writing authority."""
    model_config = ConfigDict(extra="forbid")
    mode: str = "cursor_chat"
    worker_id: str = "agent-01"
    owner: str | None = None


class PollingSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_seconds: int = 30
    max_backoff_seconds: int = 300
    overlap_seconds: int = 90
    reconcile_every_ticks: int = 5


class LimitsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_rounds_per_task: int = 10
    max_revisions_per_request: int = 3
    task_timeout_seconds: int = 7200
    model_call_timeout_seconds: int = 120
    executor_timeout_seconds: int = 3600
    max_input_tokens: int = 30000
    max_output_tokens: int = 4000
    budget_usd_per_task: float | None = 5.0
    max_model_calls_per_task: int = 20


class LoopSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_seconds: int = 10
    running_dir: str | None = None

    @field_validator("interval_seconds")
    @classmethod
    def interval_ok(cls, value: int) -> int:
        if value < 1:
            raise ValueError("loop.interval_seconds deve ser >= 1")
        return value


class PolicySection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_push: bool = True
    allow_merge: bool = False
    allow_deploy: bool = False
    allow_secret_exfil: bool = False


class ProgressSection(BaseModel):
    """Cadência já usada pela tag PULSE. O poller não publica sozinho."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_minutes: int = 15

    @field_validator("interval_minutes")
    @classmethod
    def interval_ok(cls, value: int) -> int:
        if value < 1:
            raise ValueError("progress.interval_minutes deve ser >= 1")
        return value


class AlertsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    webhook_url_env: str = "DISCORD_WEBHOOK_URL"
    username: str | None = "ia-orchestrator"
    events: list[str] = Field(
        default_factory=lambda: [
            "envelope_arrived",
            "request_claimed",
            "execution_started",
            "result_delivered",
            "task_completed",
            "quarantine",
            "git_error",
        ]
    )


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    project_id: str
    github: GitHubSection
    artifacts: ArtifactsSection = Field(default_factory=ArtifactsSection)
    workspace: WorkspaceSection
    context: ContextSection = Field(default_factory=ContextSection)
    orchestrator: OrchestratorSection = Field(default_factory=OrchestratorSection)
    executor: ExecutorSection = Field(default_factory=ExecutorSection)
    agent: AgentSection = Field(default_factory=AgentSection)
    polling: PollingSection = Field(default_factory=PollingSection)
    loop: LoopSection = Field(default_factory=LoopSection)
    progress: ProgressSection = Field(default_factory=ProgressSection)
    limits: LimitsSection = Field(default_factory=LimitsSection)
    policy: PolicySection = Field(default_factory=PolicySection)
    pricing: PricingSection = Field(default_factory=PricingSection)
    alerts: AlertsSection = Field(default_factory=AlertsSection)
    source_path: str | None = None

    @model_validator(mode="after")
    def fill_defaults(self) -> ProjectConfig:
        if not self.artifacts.repository:
            self.artifacts.repository = self.github.repository
        if not self.orchestrator.owner:
            self.orchestrator.owner = socket.gethostname()
        if not self.executor.owner:
            self.executor.owner = socket.gethostname()
        if not self.agent.owner:
            self.agent.owner = socket.gethostname()
        if self.executor.timeout_seconds is None:
            self.executor.timeout_seconds = self.limits.executor_timeout_seconds
        return self

    @property
    def namespace(self) -> str:
        return routing_namespace(self.github.host, self.github.repository, self.project_id)

    def artifacts_repo(self) -> str:
        return self.artifacts.repository or self.github.repository

    def resolved_repo_label(self) -> str:
        return f"{self.github.host}/{self.github.repository}"

    def token(self) -> str:
        name = self.github.token_env
        value = os.environ.get(name, "")
        if not value:
            raise PolicyError(f"credencial ausente: variável {name} não definida")
        return value

    def model_api_key(self) -> str:
        name = self.orchestrator.api_key_env
        if not name:
            raise PolicyError("orchestrator.api_key_env não configurado")
        value = os.environ.get(name, "")
        if not value:
            raise PolicyError(f"credencial ausente: variável {name} não definida")
        return value

    def workspace_root(self) -> Path:
        return Path(self.workspace.root).expanduser().resolve()


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    projects: dict[str, str] = Field(default_factory=dict)  # id -> config path


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise UsageError(f"ficheiro não encontrado: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UsageError(f"YAML inválido: {path}")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_project_config(path: Path) -> ProjectConfig:
    cfg = ProjectConfig.model_validate(load_yaml(path))
    cfg.source_path = str(path)
    return cfg


def registry_path(home: Path | None = None) -> Path:
    return (home or default_home()) / "registry.yaml"


def load_registry(home: Path | None = None) -> Registry:
    path = registry_path(home)
    if not path.is_file():
        return Registry()
    return Registry.model_validate(load_yaml(path))


def save_registry(registry: Registry, home: Path | None = None) -> None:
    save_yaml(registry_path(home), registry.model_dump())


def resolve_project(project_id: str, home: Path | None = None) -> ProjectConfig:
    if not project_id:
        raise UsageError("indique --project <id>; o repositório não é inferido do cwd")
    registry = load_registry(home)
    path = registry.projects.get(project_id)
    if not path:
        raise UsageError(
            f"projecto '{project_id}' não está cadastrado. "
            "Use: ia-orchestrator project add --project ... --repo owner/repo --workspace /caminho"
        )
    cfg = load_project_config(Path(path))
    if cfg.project_id != project_id:
        raise UsageError(
            f"project_id no ficheiro ({cfg.project_id}) difere do --project ({project_id})"
        )
    return cfg


def data_dir(cfg: ProjectConfig, home: Path | None = None) -> Path:
    root = home or default_home()
    path = root / "projects" / cfg.project_id / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path(cfg: ProjectConfig, home: Path | None = None) -> Path:
    return data_dir(cfg, home) / "state.sqlite"


def example_config_dict(
    project_id: str,
    repository: str,
    workspace: str,
    *,
    host: str = "github.com",
) -> dict[str, Any]:
    token_env = "GITHUB_TOKEN_" + project_id.upper().replace("-", "_")
    return {
        "schema_version": 1,
        "project_id": project_id,
        "github": {
            "host": host,
            "repository": repository,
            "token_env": token_env,
            "allowed_senders": {
                "human": ["usuario-responsavel"],
                "orchestrator": ["bot-orquestrador"],
                "executor": ["bot-executor"],
                "agent": ["bot-agent"],
            },
        },
        "artifacts": {"repository": repository},
        "workspace": {"root": workspace},
        "context": {
            "proposal": "docs/proposta.md",
            "source_of_truth": "source_of_truth.json",
            "instructions": "AGENTS.md",
            "required": [],
        },
        "orchestrator": {
            "mode": "simulated",
            "provider": "simulated",
            "model": "modelo-configurado",
            "api_key_env": "LLM_API_KEY",
            "worker_id": f"orchestrator-{project_id}",
            "owner": socket.gethostname(),
        },
        "executor": {
            "mode": "simulated",
            "command": [],
            "worker_id": f"executor-{project_id}",
            "owner": socket.gethostname(),
        },
        "agent": {"mode": "cursor_chat", "worker_id": f"agent-{project_id}", "owner": socket.gethostname()},
        "polling": {"interval_seconds": 30, "max_backoff_seconds": 300},
        "loop": {"interval_seconds": 10},
        "limits": {
            "max_rounds_per_task": 10,
            "max_revisions_per_request": 3,
            "task_timeout_seconds": 7200,
            "model_call_timeout_seconds": 120,
            "max_input_tokens": 30000,
            "max_output_tokens": 4000,
            "budget_usd_per_task": 5.0,
        },
        "policy": {"allow_push": True, "allow_merge": False, "allow_deploy": False},
        "progress": {"enabled": True, "interval_minutes": 15},
        "pricing": {"currency": "usd", "models": {}},
        "alerts": {
            "enabled": False,
            "webhook_url_env": "DISCORD_WEBHOOK_URL",
            "username": "ia-orchestrator",
            "events": [
                "envelope_arrived",
                "request_claimed",
                "execution_started",
                "result_delivered",
                "task_completed",
                "quarantine",
                "git_error",
            ],
        },
    }
