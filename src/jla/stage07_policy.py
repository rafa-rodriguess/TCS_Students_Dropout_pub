from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from .audit import assert_score_contract, mechanism_respects_clock, policy_contrasts
from .science import DELTA, EPS, KEYS, active_from_recency, observed_week_table, sha256_file, survival_at_18


def run(ctx) -> dict:
    scores = ctx.results / "private" / "pp_test_scores.csv"
    model_path = ctx.models / "hazard.joblib"
    if not scores.exists() or not model_path.exists():
        return {"status": "NOT_RUN_SCIENCE", "message": "política não executada; escores ou modelo ausentes"}
    frame = pd.read_csv(scores)
    assert_score_contract(frame)
    hazard = frame["hazard_hat"].to_numpy(dtype=float)
    active = active_from_recency(frame)
    shock = hazard.copy()
    shock[active] = np.clip(hazard[active] * (1.0 - DELTA), EPS, 1.0 - EPS)
    model = joblib.load(model_path)
    clock = mechanism_respects_clock(frame, hazard, model)
    if not clock["action_unchanged"] or not clock["outside_unchanged"]:
        return {"status": "FAIL", "message": "mecanismo alterou a semana da ação ou uma semana fora da resposta"}
    base = survival_at_18(frame, hazard)
    shock_s = survival_at_18(frame, shock)
    mech_s = survival_at_18(frame, clock["mech"])
    both = base.merge(shock_s[KEYS + ["S"]], on=KEYS, suffixes=("_base", "_shock"))
    both = both.merge(mech_s[KEYS + ["S"]].rename(columns={"S": "S_mech"}), on=KEYS)
    both["dS_shock"] = both["S_shock"] - both["S_base"]
    both["dS_mech"] = both["S_mech"] - both["S_base"]
    both["female"] = both["gender"].astype(str).eq("F")
    private = ctx.results / "private"
    private.mkdir(parents=True, exist_ok=True)
    both.to_csv(private / "r18.csv", index=False)
    scenario = frame[KEYS + ["week", "s_star"]].copy()
    scenario["h_base"] = hazard
    scenario["h_shock"] = shock
    scenario["h_mech"] = clock["mech"]
    scenario_path = private / "scenario_rows.csv"
    scenario.to_csv(scenario_path, index=False)
    hashes = {
        "pp_test_scores.csv": sha256_file(scores),
        "scenario_rows.csv": sha256_file(scenario_path),
        "r18.csv": sha256_file(private / "r18.csv"),
        "hazard.joblib": sha256_file(model_path),
    }
    (private / "scenario_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    curve = observed_week_table(frame, hazard).rename(columns={"mean_predicted_S_among_observed": "mean_predicted_S_base"})
    curve["mean_predicted_S_shock"] = observed_week_table(frame, shock)["mean_predicted_S_among_observed"].to_numpy()
    curve["mean_predicted_S_mech"] = observed_week_table(frame, clock["mech"])["mean_predicted_S_among_observed"].to_numpy()
    curve.to_csv(ctx.curves / "survival_week.csv", index=False)
    payload = policy_contrasts(both)
    (ctx.results / "p3_metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    return {"status": "PASS", "message": "choque e mecanismo no mesmo R18; curva pública sem identificador"}
