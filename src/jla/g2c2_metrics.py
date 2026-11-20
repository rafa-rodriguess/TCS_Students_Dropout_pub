"""Cálculo sintético das métricas G2c.2.

Não lê OULAD, não baixa dados e não consulta os alvos agregados.
O único ajuste permitido aqui é o ensaio em memória que prova o caminho.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from .audit import ipcw_weights, landmark_roles
from .science import (
    ALPHA_FIRST,
    ALPHA_SECOND,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    DELTA,
    EPS,
    FEATURES,
    KEYS,
    active_from_recency,
    attach_s_star,
    censoring_g,
    clustered_auc,
    ece15,
    ess,
    fit_one,
    gap,
    observed_week_table,
    response_plan,
    rewritten_features,
    survival_at_18,
)


def landmark_gate(g18: float) -> str:
    if not np.isfinite(g18) or g18 < 0.05:
        return "NO-GO"
    return "PASS"


def common_support_rows(left: pd.DataFrame, right: pd.DataFrame) -> int:
    keys = KEYS + ["week"]
    merged = left[keys].drop_duplicates().merge(right[keys].drop_duplicates(), on=keys, how="inner")
    return int(len(merged))


def _feature_rows(students: range, event_students: set[int]) -> pd.DataFrame:
    rows = []
    for student in students:
        for week in range(4):
            rows.append(
                {
                    "id_student": student,
                    "code_module": "AAA",
                    "code_presentation": "2014J",
                    "week": week,
                    "event": int(student in event_students and week == 3),
                    "lag_available": int(week > 0),
                    "total_clicks_lag": float(week),
                    "studied_credits": 60,
                    "num_of_prev_attempts": 0,
                    "recency_lag": 0.0,
                    "streak_lag": float(week > 0),
                    "submitted_lag": 0.0,
                    "highest_education": "A Level or Equivalent",
                    "age_band": "0-35",
                    "gender": "F" if student % 2 == 0 else "M",
                }
            )
    return pd.DataFrame(rows)


def _survival_frame() -> tuple[pd.DataFrame, np.ndarray]:
    rows = []
    for student in (1, 2):
        for week in range(19):
            rows.append(
                {
                    "id_student": student,
                    "code_module": "AAA",
                    "code_presentation": "2014J",
                    "week": week,
                    "gender": "F" if student == 1 else "M",
                    "recency": 1 if week == 1 else 0,
                    "total_clicks": 1.0 if week == 1 else 0.0,
                    "streak": 1 if week == 1 else 0,
                    "submitted_this_week": 0,
                }
            )
    frame = pd.DataFrame(rows)
    hazard = np.full(len(frame), 0.05)
    return frame, hazard


def synthetic_end_to_end() -> dict:
    train = _feature_rows(range(10), {0, 2, 4, 6, 8})
    test = _feature_rows(range(10, 15), {10, 12})
    model = fit_one(train)
    probability = model.predict_proba(test[FEATURES])[:, 1]
    y = test["event"].to_numpy(dtype=int)
    scored = test[["id_student", "event"]].copy()
    scored["hazard_hat"] = probability
    auc = clustered_auc(scored, seed=BOOTSTRAP_SEED, draws=BOOTSTRAP_DRAWS)
    ece = ece15(y, probability)
    support = common_support_rows(train, test)
    enr = pd.DataFrame(
        {
            "id_student": [1, 2, 3, 4],
            "code_module": ["AAA"] * 4,
            "code_presentation": ["2014J"] * 4,
            "event_withdrawn": [1, 0, 1, 0],
            "t_event_week": [12, np.nan, 4, np.nan],
            "t_final_week": [12, 20, 4, 20],
        }
    )
    roles = landmark_roles(enr)
    g = censoring_g(enr)
    gate = landmark_gate(g[18])
    cases = roles.loc[roles["y"].eq(1), "t_event_week"].to_numpy(dtype=float)
    weights = ipcw_weights(cases, g, 18, int(roles["y"].eq(0).sum())) if gate == "PASS" else None
    frame, hazard = _survival_frame()
    survival = survival_at_18(frame, hazard)
    weekly = observed_week_table(frame, hazard)
    monotone = bool(np.all(np.diff(weekly["mean_predicted_S_among_observed"].to_numpy(dtype=float)) <= 1e-12))
    active = active_from_recency(frame)
    shocked = hazard.copy()
    shocked[active] = np.clip(hazard[active] * (1.0 - DELTA), EPS, 1.0 - EPS)
    mechanism = _feature_rows(range(1), set())
    mechanism["recency"] = np.where(mechanism["week"].eq(0), 1, 0)
    mechanism["total_clicks"] = np.where(mechanism["week"].eq(1), 3.0, 0.0)
    mechanism["streak"] = 0
    mechanism["submitted_this_week"] = 0
    attached = attach_s_star(mechanism)
    plan = response_plan(attached)
    base = rewritten_features(attached, plan, ALPHA_FIRST, ALPHA_SECOND, enabled=False)
    changed = rewritten_features(attached, plan, ALPHA_FIRST, ALPHA_SECOND, enabled=True)
    response = plan["first_response"].to_numpy() | plan["second_response"].to_numpy()
    female = survival["gender"].eq("F").to_numpy()
    return {
        "source": "synthetic",
        "oulad_fit": False,
        "targets_used": False,
        "auc": float(roc_auc_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "ece15": float(ece[-1]["ece"]),
        "common_support_rows": support,
        "landmark_cases": int(roles["y"].eq(1).sum()),
        "landmark_controls": int(roles["y"].eq(0).sum()),
        "landmark_excluded": int(roles["y"].lt(0).sum()),
        "g18": float(g[18]),
        "landmark_status": gate,
        "ess_cases": None if weights is None else float(ess(weights[0])),
        "ess_controls": None if weights is None else float(ess(weights[1])),
        "r18": int(survival["week"].eq(18).sum()) if "week" in survival.columns else int(len(survival)),
        "shock_changes_active_weeks": bool(np.any(shocked[active] < hazard[active])),
        "mechanism_changes_response_only": bool(response.any() and np.allclose(base.loc[~response, "total_clicks_lag"], changed.loc[~response, "total_clicks_lag"])),
        "fixed_cohort_nonincreasing": monotone,
        "variable_composition_label": weekly["prohibition"].iloc[0],
        "gap_f_minus_m": float(gap(survival["S"].to_numpy(dtype=float), female)),
        "bootstrap_draws": int(auc["draws"]),
        "bootstrap_model": "fixed",
        "bootstrap_n_valid": int(auc["n_valid"]),
    }
