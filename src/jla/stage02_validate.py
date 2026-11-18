from __future__ import annotations

import csv

from .protocol import load_protocol
from .science import sha256_file
from .stage01_download import CSV_NAMES

REQUIRED_COLUMNS = {
    "studentInfo.csv": {"id_student", "code_module", "code_presentation", "final_result", "gender"},
    "studentRegistration.csv": {"id_student", "code_module", "code_presentation", "date_unregistration"},
    "studentVle.csv": {"id_student", "code_module", "code_presentation", "date", "sum_click"},
}


def run(ctx) -> dict:
    protocol = load_protocol()
    hashes = protocol.get("hashes") or {}
    observed = {}
    unconfirmed = []
    for name in CSV_NAMES:
        path = ctx.raw / name
        if not path.exists():
            return {"status": "FAIL", "message": f"arquivo ausente: {name}"}
        needed = REQUIRED_COLUMNS.get(name)
        if needed:
            with path.open(newline="", encoding="utf-8") as handle:
                header = set(next(csv.reader(handle)))
            if not needed <= header:
                return {"status": "FAIL", "message": f"schema incompleto em {name}"}
        got = sha256_file(path)
        observed[name] = got
        expected = hashes.get(name)
        if expected is None:
            unconfirmed.append(name)
            continue
        if got != expected:
            return {"status": "FAIL", "message": f"hash divergente em {name}; esperado não foi alterado", "got": got}
    if "zip" not in hashes or hashes.get("zip") is None:
        unconfirmed.append("zip")
    return {"status": "PASS", "message": "cinco hashes conhecidos conferem", "unconfirmed": unconfirmed, "observed_unconfirmed_only": {name: observed[name] for name in unconfirmed if name in observed}}
