from __future__ import annotations

import csv
import json

from .csv_canonical import decide
from .protocol import load_protocol
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
    decisions = []
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
        decision = decide(path, name, hashes.get(name))
        observed[name] = decision.get("observed")
        if decision["status"] == "FAIL":
            return {"status": "FAIL", "message": decision["message"], "got": decision.get("observed"), "file": name}
        if decision["status"] == "PENDING":
            unconfirmed.append(name)
        decisions.append(decision)
    if "zip" not in hashes or hashes.get("zip") is None:
        unconfirmed.append("zip")
        zip_path = ctx.raw / "oulad.zip"
        if zip_path.exists():
            from .csv_canonical import sha_file

            observed["oulad.zip"] = sha_file(zip_path)
    ctx.logs.mkdir(parents=True, exist_ok=True)
    (ctx.logs / "csv_gate.json").write_text(
        json.dumps({"decisions": decisions, "unconfirmed": unconfirmed, "observed_raw": observed}, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "PASS",
        "message": "gates de hash conferem; pendências formais preservadas",
        "unconfirmed": unconfirmed,
        "observed_unconfirmed_only": {name: observed[name] for name in unconfirmed if name in observed},
        "validation": [{key: row[key] for key in ("file", "status", "validation_mode", "observed", "expected") if key in row} for row in decisions],
    }
