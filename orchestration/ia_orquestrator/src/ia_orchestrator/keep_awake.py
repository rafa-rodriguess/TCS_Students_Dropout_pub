#!/usr/bin/env python3
"""Mantém o Mac acordado e a sessão ativa enquanto o monitor estiver vivo.

No macOS, `caffeinate -u` sozinho mantém a asserção de utilizador ativo por
apenas alguns segundos quando não há timeout/utility. Por isso este helper
executa uma pequena utility-vigia sob `caffeinate`; assim as asserções de
display, idle sleep e user activity permanecem válidas durante toda a vida
do monitor/sentinela.

Isto evita o lock automático por inatividade/screen saver enquanto o monitor
está ativo. Não tenta contornar lock manual nem políticas MDM/administrativas.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable


def caffeinate_argv(parent_pid: int) -> list[str]:
    """Comando macOS que mantém as asserções enquanto o monitor-pai existir.

    O shell é passado como *utility* do caffeinate. Nesse modo, inclusive a
    asserção `-u` acompanha a duração da utility, evitando o timeout padrão
    curto da asserção de "user active".
    """
    return [
        "caffeinate",
        "-d",  # não deixar o ecrã adormecer
        "-i",  # não deixar o sistema adormecer por inatividade
        "-u",  # declarar o utilizador como ativo durante a utility
        "/bin/sh",
        "-c",
        'while kill -0 "$1" 2>/dev/null; do sleep 1; done',
        "ia-orchestrator-monitor",
        str(parent_pid),
    ]


def stop_process(proc: subprocess.Popen[bytes], *, timeout: float = 5) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def supervise(
    proc: subprocess.Popen[bytes],
    parent_pid: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    getppid: Callable[[], int] = os.getppid,
    interval: float = 1.0,
) -> int:
    """Espera o caffeinate. Sai se o pai deixar de ser `parent_pid`."""
    while True:
        code = proc.poll()
        if code is not None:
            return int(code)
        if getppid() != parent_pid:
            stop_process(proc)
            return 0
        sleep(interval)


def main() -> int:
    if sys.platform != "darwin":
        print("keep_awake: caffeinate só existe no macOS; a sair.", flush=True)
        return 0
    parent = os.getppid()
    print(
        f"keep_awake: macOS idle-lock inhibition active while monitor PID {parent} is alive.",
        flush=True,
    )
    try:
        proc = subprocess.Popen(caffeinate_argv(parent))
    except FileNotFoundError:
        print("keep_awake: caffeinate não encontrado.", flush=True)
        return 0
    try:
        return supervise(proc, parent)
    except KeyboardInterrupt:
        stop_process(proc)
        print("\nkeep_awake: parado.", flush=True)
        return 0


def spawn() -> subprocess.Popen[bytes]:
    """Lança este módulo num processo separado."""
    return subprocess.Popen([sys.executable, "-m", "ia_orchestrator.keep_awake"])


if __name__ == "__main__":
    sys.exit(main())
