from __future__ import annotations

import json

import pandas as pd

from .audit import scenario_gender

TOLERANCE = 1e-12
SCENARIOS = (
    ("shock", "S_shock", "dS_shock", "delta_s_shock", "delta_gap_shock"),
    ("mechanism", "S_mech", "dS_mech", "delta_s_mechanism", "delta_gap_mechanism"),
)


def _female(table: pd.DataFrame) -> pd.Series:
    column = table["female"]
    if column.dtype == bool:
        return column
    return column.astype(str).str.strip().str.lower().isin(["1", "true", "t"])


def _weighted_mean(table: pd.DataFrame, column: str, female: pd.Series) -> float | None:
    n_female = int(female.sum())
    n_male = int((~female).sum())
    if n_female == 0 or n_male == 0:
        return None
    female_mean = float(table.loc[female, column].mean())
    male_mean = float(table.loc[~female, column].mean())
    return (n_female * female_mean + n_male * male_mean) / (n_female + n_male)


def run(ctx) -> dict:
    path = ctx.results / "private" / "r18.csv"
    metrics_path = ctx.results / "p3_metrics.json"
    if not path.exists() or not metrics_path.exists():
        missing = "R18" if not path.exists() else "p3_metrics.json"
        return {"status": "FAIL", "message": f"equidade sem {missing}"}
    table = pd.read_csv(path)
    needed = {"dS_shock", "dS_mech", "S_base", "S_shock", "S_mech", "female", "id_student"}
    if not needed <= set(table.columns):
        return {"status": "FAIL", "message": "R18 sem os dois contrastes"}
    saved = json.loads(metrics_path.read_text(encoding="utf-8"))
    female = _female(table)
    table = table.copy()
    table["female"] = female
    summary = {
        "n_enrollments": int(len(table)),
        "n_students": int(table["id_student"].nunique()),
        "disability": "NOT_SUPPORTED",
        "causal_claim": False,
    }
    failures = []
    for name, scenario, contrast, delta_key, gap_key in SCENARIOS:
        weighted = _weighted_mean(table, contrast, female)
        if weighted is None or int(female.sum()) < 1 or int((~female).sum()) < 1:
            failures.append(f"{name}: suporte insuficiente")
            continue
        block = scenario_gender(table, scenario, contrast)
        summary[name] = block
        if delta_key not in saved or gap_key not in saved:
            failures.append(f"{name}: campo P3 ausente")
            continue
        if abs(weighted - float(saved[delta_key])) > TOLERANCE:
            failures.append(f"{name}: deltaS nao recupera o P3")
        if abs(float(block["delta_gap"]) - float(saved[gap_key])) > TOLERANCE:
            failures.append(f"{name}: deltaGap nao recupera o P3")
    summary["status"] = "FAIL" if failures else "PASS"
    (ctx.results / "equity.json").write_text(json.dumps(summary), encoding="utf-8")
    if failures:
        return {"status": "FAIL", "message": "; ".join(failures)}
    return {"status": "PASS", "message": "medias F/M recuperam o P3; deficiencia fora do modelo"}
