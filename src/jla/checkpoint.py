from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import PACKAGE_ROOT, Context


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_fingerprint() -> str:
    digest = hashlib.sha256()
    paths = [PACKAGE_ROOT / "orquestrator.py", PACKAGE_ROOT / "config" / "protocol.yaml"]
    paths.extend(sorted((PACKAGE_ROOT / "src" / "jla").glob("*.py")))
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def library_fingerprint() -> str:
    import joblib
    import numpy
    import pandas
    import sklearn

    payload = f"{numpy.__version__}|{pandas.__version__}|{sklearn.__version__}|{joblib.__version__}"
    return _sha_bytes(payload.encode())


def fingerprint() -> str:
    return _sha_bytes(f"{code_fingerprint()}|{library_fingerprint()}".encode())


def load_state(ctx: Context) -> dict:
    path = ctx.checkpoints / "state.json"
    if not path.exists():
        return {"stages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(ctx: Context, state: dict) -> None:
    ctx.checkpoints.mkdir(parents=True, exist_ok=True)
    (ctx.checkpoints / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_log(ctx: Context, record: dict) -> None:
    ctx.logs.mkdir(parents=True, exist_ok=True)
    with (ctx.logs / "stages.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def input_token(ctx: Context, stage: str) -> str:
    from .science import sha256_file
    from .stage01_download import CSV_NAMES

    mapping = {
        "00": [PACKAGE_ROOT / "requirements.lock"],
        "01": [PACKAGE_ROOT / "config" / "protocol.yaml"],
        "02": [ctx.raw / name for name in CSV_NAMES],
        "03": [ctx.raw / name for name in CSV_NAMES],
        "04": [ctx.processed / "enrollments.csv", ctx.processed / "person_period.csv"],
        "05": [ctx.processed / "person_period_split.csv", ctx.processed / "enrollments.csv", ctx.processed / "enroll_train_keys.csv"],
        "06": [ctx.processed / "enrollments.csv", ctx.processed / "enroll_train_keys.csv"],
        "07": [ctx.results / "private" / "pp_test_scores.csv", ctx.models / "hazard.joblib"],
        "08": [ctx.results / "private" / "pp_test_scores.csv", ctx.results / "private" / "r18.csv", ctx.models / "hazard.joblib"],
        "09": [ctx.results / "private" / "r18.csv"],
        "10": [ctx.results / "p1_metrics.json", ctx.results / "p2_metrics.json", ctx.results / "p3_metrics.json", ctx.results / "censoring.json", ctx.results / "operator_tests.json", ctx.results / "equity.json", ctx.results / "landmark.json"],
    }
    digest = hashlib.sha256()
    for path in mapping.get(stage, []):
        digest.update(path.name.encode())
        digest.update(sha256_file(path).encode() if path.exists() else b"MISSING")
    return digest.hexdigest()


def output_token(ctx: Context, stage: str) -> str:
    from .science import sha256_file

    mapping = {
        "03": [ctx.processed / "person_period.csv"],
        "04": [ctx.processed / "enroll_train_keys.csv", ctx.processed / "enroll_test_keys.csv", ctx.processed / "person_period_split.csv"],
        "05": [ctx.results / "private" / "pp_test_scores.csv", ctx.results / "landmark.json", ctx.models / "hazard.joblib"],
        "06": [ctx.results / "censoring.json"],
        "07": [ctx.results / "p3_metrics.json", ctx.curves / "survival_week.csv", ctx.results / "private" / "r18.csv", ctx.results / "private" / "scenario_rows.csv", ctx.results / "private" / "scenario_hashes.json"],
        "08": [ctx.results / "operator_tests.json", ctx.results / "public_examples.json"],
        "09": [ctx.results / "equity.json"],
        "10": [ctx.results / "manifest.json"],
    }
    digest = hashlib.sha256()
    for path in mapping.get(stage, []):
        digest.update(sha256_file(path).encode() if path.exists() else b"MISSING")
    return digest.hexdigest()


def reusable(state: dict, stage: str, current: str, inputs: str, outputs: str) -> bool:
    row = state.get("stages", {}).get(stage)
    return bool(
        row
        and row.get("status") == "PASS"
        and row.get("fingerprint") == current
        and row.get("input_token") == inputs
        and row.get("output_token") == outputs
    )


def invalidate_from(state: dict, stage: str, order: list[str]) -> None:
    if stage not in order:
        return
    start = order.index(stage)
    for name in order[start:]:
        state.get("stages", {}).pop(name, None)
