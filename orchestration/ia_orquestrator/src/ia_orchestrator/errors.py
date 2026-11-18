"""Excepções e códigos de saída da CLI."""

from __future__ import annotations


EX_OK = 0
EX_ERROR = 1
EX_USAGE = 2
EX_AUTH = 3
EX_NOTFOUND = 4
EX_LOCK = 5
EX_PROTOCOL = 6
EX_POLICY = 7
EX_NETWORK = 8
EX_LIMIT = 9


class OrchestratorError(Exception):
    exit_code = EX_ERROR


class UsageError(OrchestratorError):
    exit_code = EX_USAGE


class AuthError(OrchestratorError):
    exit_code = EX_AUTH


class NotFoundError(OrchestratorError):
    exit_code = EX_NOTFOUND


class LockError(OrchestratorError):
    exit_code = EX_LOCK


class ProtocolError(OrchestratorError):
    exit_code = EX_PROTOCOL


class PolicyError(OrchestratorError):
    exit_code = EX_POLICY


class NetworkError(OrchestratorError):
    exit_code = EX_NETWORK


class LimitError(OrchestratorError):
    exit_code = EX_LIMIT


class QuarantineError(ProtocolError):
    """Mensagem observada mas não executável."""
