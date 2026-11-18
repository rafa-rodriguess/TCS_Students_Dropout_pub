"""Estados de tarefa, entrega e execução, com tabela de transições."""

from __future__ import annotations

from enum import Enum

from ia_orchestrator.errors import ProtocolError
from ia_orchestrator.protocol import CONTROL_RESULT_TYPES, RECOVERY_CONTROL_TYPES, MessageType


class TaskState(str, Enum):
    NEW = "NEW"
    WAITING_EXECUTOR = "WAITING_EXECUTOR"
    RUNNING = "RUNNING"
    WAITING_ORCHESTRATOR = "WAITING_ORCHESTRATOR"
    WAITING_INPUT = "WAITING_INPUT"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
ACTIVE_WORK = {
    TaskState.WAITING_EXECUTOR,
    TaskState.RUNNING,
    TaskState.WAITING_ORCHESTRATOR,
    TaskState.WAITING_INPUT,
}


class RequestState(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ExecutionState(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class DeliveryState(str, Enum):
    PENDING = "PENDING"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


# (from_state, message_type) -> to_state  | None = ignore without transition
# Guards are applied in apply_transition().
TRANSITIONS: dict[tuple[TaskState, str], TaskState] = {
    (TaskState.NEW, MessageType.REQUEST.value): TaskState.WAITING_EXECUTOR,
    (TaskState.NEW, MessageType.SEND_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.NEW, MessageType.GET_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.NEW, MessageType.PAUSE.value): TaskState.PAUSED,
    (TaskState.NEW, MessageType.CANCEL.value): TaskState.CANCELLED,
    (TaskState.WAITING_EXECUTOR, MessageType.ACK.value): TaskState.RUNNING,
    (TaskState.WAITING_EXECUTOR, MessageType.SEND_FILE_READY.value): TaskState.RUNNING,
    (TaskState.WAITING_EXECUTOR, MessageType.PROGRESS.value): TaskState.RUNNING,
    # result inclui sucesso e bloqueio que exige decisão. Não fecha a tarefa.
    (TaskState.WAITING_EXECUTOR, MessageType.RESULT.value): TaskState.WAITING_ORCHESTRATOR,
    (TaskState.WAITING_EXECUTOR, MessageType.QUESTION.value): TaskState.WAITING_INPUT,
    (TaskState.WAITING_EXECUTOR, MessageType.ERROR.value): TaskState.WAITING_ORCHESTRATOR,
    (TaskState.WAITING_EXECUTOR, MessageType.PAUSE.value): TaskState.PAUSED,
    (TaskState.WAITING_EXECUTOR, MessageType.CANCEL.value): TaskState.CANCELLED,
    (TaskState.RUNNING, MessageType.PROGRESS.value): TaskState.RUNNING,
    (TaskState.RUNNING, MessageType.SEND_FILE_READY.value): TaskState.RUNNING,
    # O mesmo result blocked libera o claim local; a tarefa fica à espera de nova request.
    (TaskState.RUNNING, MessageType.RESULT.value): TaskState.WAITING_ORCHESTRATOR,
    (TaskState.RUNNING, MessageType.QUESTION.value): TaskState.WAITING_INPUT,
    (TaskState.RUNNING, MessageType.ERROR.value): TaskState.WAITING_ORCHESTRATOR,
    (TaskState.RUNNING, MessageType.PAUSE.value): TaskState.PAUSED,
    (TaskState.RUNNING, MessageType.CANCEL.value): TaskState.CANCELLED,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.REQUEST.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.SEND_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.GET_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.REVIEW.value): TaskState.WAITING_ORCHESTRATOR,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.COMPLETE.value): TaskState.COMPLETED,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.QUESTION.value): TaskState.WAITING_INPUT,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.PAUSE.value): TaskState.PAUSED,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.CANCEL.value): TaskState.CANCELLED,
    (TaskState.WAITING_ORCHESTRATOR, MessageType.ERROR.value): TaskState.FAILED,
    (TaskState.WAITING_INPUT, MessageType.REQUEST.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_INPUT, MessageType.SEND_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_INPUT, MessageType.GET_FILE.value): TaskState.WAITING_EXECUTOR,
    (TaskState.WAITING_INPUT, MessageType.ANSWER.value): TaskState.WAITING_INPUT,  # resolved by guard
    (TaskState.WAITING_INPUT, MessageType.PAUSE.value): TaskState.PAUSED,
    (TaskState.WAITING_INPUT, MessageType.CANCEL.value): TaskState.CANCELLED,
    (TaskState.PAUSED, MessageType.RESUME.value): TaskState.PAUSED,  # restored by previous_state
    (TaskState.PAUSED, MessageType.CANCEL.value): TaskState.CANCELLED,
}


def apply_transition(
    current: TaskState,
    message_type: str,
    *,
    previous: TaskState | None = None,
    answer_resumes_to: TaskState | None = None,
    allow_late: bool = False,
) -> TaskState | None:
    """Devolve o novo estado ou None se a mensagem for tardia/ignorável.

    Não executa efeitos. Testes devem cobrir esta tabela.
    """
    if current in TERMINAL:
        if allow_late:
            return current
        if message_type in {
            MessageType.RESULT.value,
            MessageType.ACK.value,
            MessageType.PROGRESS.value,
            MessageType.ERROR.value,
            MessageType.CONTROL_RESULT.value,
            MessageType.SEND_FILE_READY.value,
        }:
            return current  # tardio: registrar, não reactivar
        raise ProtocolError(f"transição recusada: tarefa {current.value} ignora {message_type} como acção")

    if message_type == MessageType.TASK_OPEN.value:
        if current != TaskState.NEW:
            raise ProtocolError("task_open duplicado")
        return TaskState.NEW

    # Recovery controls are side-band commands. They must never replace or
    # advance the lifecycle of the primary task that is already running.
    if message_type in RECOVERY_CONTROL_TYPES or message_type in CONTROL_RESULT_TYPES:
        return current

    if current == TaskState.WAITING_INPUT and message_type == MessageType.ANSWER.value:
        return answer_resumes_to or previous or TaskState.WAITING_EXECUTOR

    if current == TaskState.PAUSED and message_type == MessageType.RESUME.value:
        restored = previous or TaskState.WAITING_ORCHESTRATOR
        if restored in TERMINAL or restored == TaskState.PAUSED:
            return TaskState.WAITING_ORCHESTRATOR
        return restored

    key = (current, message_type)
    if key not in TRANSITIONS:
        if message_type == MessageType.REVIEW.value and current == TaskState.WAITING_ORCHESTRATOR:
            return current
        raise ProtocolError(f"transição inválida: {current.value} + {message_type}")
    return TRANSITIONS[key]


def decision_block(output: dict) -> bool:
    """Bloqueio que exige decisão da orquestradora.

    Publica `result` com status blocked, libera o claim e volta o host a IDLE.
    A tarefa não fecha. `transient: true` publica question, também libera o
    running/, e a tarefa fica WAITING_INPUT até answer ou nova request.
    """
    if not isinstance(output, dict) or output.get("status") != "blocked":
        return False
    return output.get("transient") is not True


def can_emit_request(state: TaskState) -> bool:
    return state in {TaskState.NEW, TaskState.WAITING_ORCHESTRATOR, TaskState.WAITING_INPUT} or state == TaskState.NEW


def blocks_new_work(state: TaskState) -> bool:
    return state in TERMINAL or state == TaskState.PAUSED
