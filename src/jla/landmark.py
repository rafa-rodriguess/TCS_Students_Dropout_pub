# Marco L=8, horizonte 18, copiado do fluxo do P2. Não ajusta modelo.

from __future__ import annotations

import numpy as np
import pandas as pd

from .audit import ipcw_weights, landmark_roles
from .science import KEYS, STATICS, censoring_g, clustered_auc, ess

FROZEN_COUNTS = {"n_cases": 576, "n_controls": 6275, "n_excluded": 435}


def cohort_frame(enr: pd.DataFrame, clicks: pd.DataFrame, submitted: pd.DataFrame):
    from .science import STATICS as statics
    from .science import add_lag, add_same_week_state, assert_lag, expand

    missing = [column for column in statics if column not in enr.columns]
    if missing:
        raise RuntimeError(f"painel sem {missing}")
    if enr[statics].isna().any().any():
        raise RuntimeError("static covariate has missing values; refusing to impute")
    frame = add_lag(add_same_week_state(expand(enr), clicks, submitted))
    assert_lag(frame)
    return frame


def snapshot_at_risk(frame: pd.DataFrame, enr: pd.DataFrame, model) -> tuple[pd.DataFrame, float | None, int]:
    from .science import FEATURES

    roles = landmark_roles(enr)
    at_risk = roles.loc[roles["at_risk"], KEYS]
    close = frame.loc[frame["week"] == 8].merge(at_risk, on=KEYS, how="inner")
    if close.empty:
        raise RuntimeError("sem fechamento da semana 8 entre quem está em risco")
    needed = KEYS + STATICS + ["total_clicks", "recency", "streak", "submitted_this_week"]
    missing = [column for column in needed if column not in close.columns]
    if missing:
        raise RuntimeError(f"fechamento da semana 8 sem {missing}")
    snap = close[needed].copy()
    snap["week"] = 9
    snap["lag_available"] = 1
    snap["total_clicks_lag"] = snap["total_clicks"]
    snap["recency_lag"] = snap["recency"]
    snap["streak_lag"] = snap["streak"]
    snap["submitted_lag"] = snap["submitted_this_week"]
    snap["hazard_hat"] = model.predict_proba(snap[FEATURES])[:, 1]
    row9 = frame.loc[frame["week"] == 9].copy()
    gap = None
    n_checked = 0
    if not row9.empty:
        row9["hazard_row"] = model.predict_proba(row9[FEATURES])[:, 1]
        agreed = snap.merge(row9[KEYS + ["hazard_row"]], on=KEYS, how="inner")
        n_checked = int(len(agreed))
        if n_checked:
            gap = float((agreed["hazard_hat"] - agreed["hazard_row"]).abs().max())
            if gap > 1e-10:
                raise RuntimeError(f"h(9) não reproduz o fechamento da semana 8: {gap}")
    return snap, gap, int(len(snap) - n_checked)


def g_from_train_at_risk(enr: pd.DataFrame, train_ids: set) -> dict[int, float]:
    train = enr.loc[enr["id_student"].isin(train_ids)].copy()
    roles = landmark_roles(train)
    at_risk = train.loc[roles["at_risk"].to_numpy()]
    if at_risk.empty:
        raise RuntimeError("treino sem matrícula em risco no marco")
    return censoring_g(at_risk)


def evaluate_landmark(enr: pd.DataFrame, frame: pd.DataFrame, model, train_ids: set, *, require_frozen: bool) -> dict:
    snap, gap, n_without_week9 = snapshot_at_risk(frame, enr, model)
    roles = landmark_roles(enr)
    labeled = roles.merge(snap[KEYS + ["hazard_hat"]], on=KEYS, how="inner")
    test = labeled.loc[~labeled["id_student"].isin(train_ids)].copy()
    n_cases = int((test["y"] == 1).sum())
    n_controls = int((test["y"] == 0).sum())
    n_excluded = int((test["y"] < 0).sum())
    g = g_from_train_at_risk(enr, train_ids)
    unweighted = None
    ipcw = None
    ess_cases = None
    ess_controls = None
    support = None
    if n_cases and n_controls:
        if test.loc[test["y"] >= 0, "hazard_hat"].isna().any():
            raise RuntimeError("há caso ou controle sem h(9)")
        observed = test.loc[test["y"] >= 0, ["id_student", "hazard_hat", "y"]].rename(columns={"y": "event"})
        unweighted = clustered_auc(observed)
        case_weeks = test.loc[test["y"] == 1, "t_event_week"].astype(int).to_numpy()
        w_case, w_control = ipcw_weights(case_weeks, g, 18, n_controls)
        cases = test.loc[test["y"] == 1, ["id_student", "hazard_hat"]].assign(event=1, w=w_case)
        controls = test.loc[test["y"] == 0, ["id_student", "hazard_hat"]].assign(event=0, w=w_control)
        ordered = pd.concat([cases, controls], ignore_index=True)
        ipcw = clustered_auc(ordered, ordered["w"].to_numpy())
        ess_cases = ess(w_case)
        ess_controls = ess(w_control)
        support = {"weight_case_max": float(w_case.max()), "weight_case_p50": float(np.median(w_case)), "weight_control": float(w_control[0])}
    if n_cases and n_controls and (ipcw is None or unweighted is None):
        raise RuntimeError("AUC ausente com casos e controles")
    counts = {"n_cases": n_cases, "n_controls": n_controls, "n_excluded": n_excluded}
    frozen_ok = (not require_frozen) or (counts == FROZEN_COUNTS and ipcw is not None)
    return {
        "snapshot_ok": True,
        "snapshot_gap": gap,
        "n_without_week9": n_without_week9,
        "n_cases": n_cases,
        "n_controls": n_controls,
        "n_excluded": n_excluded,
        "G18": g.get(18),
        "frozen_ok": frozen_ok,
        "auc": None if ipcw is None else ipcw["auc"],
        "auc_ci": None if ipcw is None else [ipcw["ci_lo"], ipcw["ci_hi"]],
        "auc_unweighted": None if unweighted is None else unweighted["auc"],
        "auc_unweighted_ci": None if unweighted is None else [unweighted["ci_lo"], unweighted["ci_hi"]],
        "ess_cases": ess_cases,
        "ess_controls": ess_controls,
        "support": support,
        "population": "snapshot_L8_test_labels_train_at_risk_G",
    }
