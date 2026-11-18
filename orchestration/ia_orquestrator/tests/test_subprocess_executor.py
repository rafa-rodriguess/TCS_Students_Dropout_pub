from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ia_orchestrator.adapters.executor import ExecutorInput, SubprocessExecutorAdapter


def test_subprocess_executor_contract(tmp_path):
    script = Path(__file__).resolve().parents[1] / "examples" / "simulated_executor.py"
    adapter = SubprocessExecutorAdapter([sys.executable, str(script)], cwd=tmp_path, timeout=10)
    payload = ExecutorInput(
        project_id="p",
        repository="o/r",
        task_id="t",
        request_id="r",
        attempt=2,
        prompt="entrega final",
        context={},
        cwd=str(tmp_path),
        idempotency_key="k",
    )
    out = adapter.run(payload)
    assert out.status == "success"
    assert out.tests and out.tests[0]["passed"]
