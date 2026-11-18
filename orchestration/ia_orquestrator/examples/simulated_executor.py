#!/usr/bin/env python3
"""Executor simulado conforme o contrato stdin JSON / stdout JSON.

Uso:
  python examples/simulated_executor.py < input.json > output.json

Não é a ferramenta real do utilizador. Integre o binário local configurando
executor.command como lista de argumentos (sem shell).
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"status": "failed", "summary": f"stdin inválido: {exc}", "errors": [str(exc)]}, sys.stdout)
        return 1
    prompt = str(payload.get("prompt", "")).lower()
    attempt = int(payload.get("attempt") or 1)
    if "crash-unknown" in prompt:
        out = {"status": "unknown", "summary": "estado desconhecido", "checkpoint": {"note": "reconciliar"}}
    elif "bloquear" in prompt or "block" in prompt:
        out = {"status": "blocked", "summary": "esclarecimento", "questions": ["Qual branch usar?"]}
    elif "falhar" in prompt or "fail" in prompt:
        out = {"status": "failed", "summary": "falha recuperável", "errors": ["comando X saiu 1"]}
    elif attempt == 1 and "final" not in prompt and "evidência" not in prompt:
        out = {"status": "success", "summary": "rascunho", "files_modified": [], "tests": []}
    else:
        out = {
            "status": "success",
            "summary": "entrega com testes",
            "files_modified": ["README.md"],
            "tests": [{"name": "demo", "passed": True, "evidence": "simulated"}],
            "shared_artifacts": [
                {
                    "repository": payload.get("repository"),
                    "path": "docs/demo.md",
                    "commit": "0" * 40,
                    "sha256": "a" * 64,
                }
            ],
            "checkpoint": {"attempt": attempt},
            "recommendation": "aguardar avaliação da orquestradora",
        }
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    print(f"simulated_executor attempt={attempt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
