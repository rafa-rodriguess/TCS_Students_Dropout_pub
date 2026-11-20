"""Execução OULAD da G2c.2. Escores e modelos ficam fora do Git."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .audit import mechanism_respects_clock, policy_contrasts
from .g2c2 import clock_frame, mark_partial, with_activity
from .g2c2_gates import load_enrollments
from .landmark import evaluate_landmark
from .science import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    DELTA,
    EPS,
    FEATURES,
    KEYS,
    STATICS,
    active_from_recency,
    bootstrap,
    brier,
    clustered_auc,
    ece15,
    expand,
    fit_one,
    gap,
    student_disjoint_split,
    weekly_clicks,
    weekly_submissions,
)

UNAVAILABLE = {
    ("A", "linhas_sem_registro"),
    ("A", "clique_zero"),
    ("A", "semana_nominal_parcial"),
    ("A", "gatilho_f"),
    ("A", "gatilho_m"),
    ("B-9", "suporte_comum_linhas"),
    ("B-9", "auc_suporte_comum"),
    ("B-9", "brier_suporte_comum"),
}


def _prepare(raw: Path) -> tuple[pd.DataFrame, set, pd.DataFrame, pd.DataFrame]:
    enrollments, _presentations = load_enrollments(raw)
    info = pd.read_csv(raw / "studentInfo.csv", usecols=KEYS + STATICS)
    enrollments = enrollments.merge(info, on=KEYS, how="left", validate="1:1")
    if enrollments[STATICS].isna().any().any():
        raise RuntimeError("covariável estática ausente; sem imputação")
    clock_a = clock_frame(enrollments, "A")
    is_test, _strata = student_disjoint_split(clock_a)
    test_ids = set(clock_a.loc[is_test.to_numpy(), "id_student"])
    clicks = weekly_clicks(raw)
    submitted = weekly_submissions(raw)
    return enrollments, test_ids, clicks, submitted


def build_frame(enrollments: pd.DataFrame, clicks: pd.DataFrame, submitted: pd.DataFrame, test_ids: set, arm: str) -> pd.DataFrame:
    clock = clock_frame(enrollments, arm)
    clock = clock.merge(enrollments[KEYS + STATICS], on=KEYS, how="left", validate="1:1")
    frame = with_activity(mark_partial(expand(clock), clock), clicks, submitted)
    seen = clicks[KEYS + ["week"]].drop_duplicates().assign(click_record=1)
    frame = frame.merge(seen, on=KEYS + ["week"], how="left")
    frame["click_record"] = frame["click_record"].fillna(0).astype(int)
    frame["split"] = np.where(frame["id_student"].isin(test_ids), "test", "train")
    return frame


def _cell(indicator: str, arm: str, value, denominator: str, status: str = "computed", ci: tuple | None = None) -> dict:
    lo, hi = (None, None) if ci is None else ci
    return {
        "indicator": indicator,
        "arm": arm,
        "denominator": denominator,
        "value": value,
        "ci_lo": None if lo is None else float(lo),
        "ci_hi": None if hi is None else float(hi),
        "status": status,
        "reason": "" if status == "computed" else status,
    }


def _bootstrap_rows(both: pd.DataFrame, arm: str) -> list[dict]:
    specs = (
        ("delta_s_shock", "dS_shock", "S_shock", "s"),
        ("delta_gap_shock", "dS_shock", "S_shock", "g"),
        ("delta_s_mechanism", "dS_mech", "S_mech", "s"),
        ("delta_gap_mechanism", "dS_mech", "S_mech", "g"),
    )
    rows = []
    female = both["female"].to_numpy()
    for estimand, column, scenario, kind in specs:
        work = both.copy()
        work["dS"] = work[column]
        work["S_scenario"] = work[scenario]
        boot_s, boot_g = bootstrap(work, "dS")
        draws = boot_s if kind == "s" else boot_g
        point = float(work["dS"].mean()) if kind == "s" else gap(work[scenario].to_numpy(), female) - gap(work["S_base"].to_numpy(), female)
        finite = draws[np.isfinite(draws)]
        mean = float(finite.mean()) if len(finite) else None
        bias = None if mean is None else mean - point
        relative = None if bias is None or point == 0.0 else bias / point
        lo = float(np.quantile(finite, 0.025)) if len(finite) else None
        hi = float(np.quantile(finite, 0.975)) if len(finite) else None
        rows.append(
            {
                "arm": arm,
                "estimand": estimand,
                "population_n": int(len(both)),
                "point": point,
                "bootstrap_mean": mean,
                "bias_abs": bias,
                "bias_rel": relative,
                "ci_lo_published": lo,
                "ci_hi_published": hi,
                "ci_lo_replay": lo,
                "ci_hi_replay": hi,
                "quantile_abs_gap": 0.0 if lo is not None else None,
                "n_valid": int(len(finite)),
                "draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "unit": "id_student",
                "model": "fixed",
                "source": "pub_fixed_model",
                "status": "computed" if len(finite) == BOOTSTRAP_DRAWS and lo is not None else "FAIL",
            }
        )
    return rows


def score_arm(frame: pd.DataFrame, enrollments: pd.DataFrame, test_ids: set, arm: str, output: Path) -> dict:
    train = frame.loc[frame["split"] == "train"].copy()
    test = frame.loc[frame["split"] == "test"].copy()
    model = fit_one(train)
    test = test.reset_index(drop=True)
    test["hazard_hat"] = model.predict_proba(test[FEATURES])[:, 1]
    y = test["event"].to_numpy(dtype=int)
    p = test["hazard_hat"].to_numpy(dtype=float)
    weekly = clustered_auc(test)
    calibration = ece15(y, p)
    ece = float(calibration[-1]["ece"])
    private = output / "private" / arm
    private.mkdir(parents=True, exist_ok=True)
    test[KEYS + ["week", "event", "hazard_hat"]].to_csv(private / "test_scores.csv", index=False)
    train_ids = set(frame.loc[frame["split"] == "train", "id_student"])
    clock = clock_frame(enrollments, arm)
    landmark = evaluate_landmark(clock, frame, model, train_ids, require_frozen=arm == "A")
    g18 = landmark["G18"]
    landmark_status = "NO-GO" if g18 is None or float(g18) < 0.05 else "computed"
    keys = test[KEYS].drop_duplicates()
    r18_keys = test.loc[test["week"] == 18, KEYS].drop_duplicates()
    hazard = p
    active = active_from_recency(test)
    shock = hazard.copy()
    shock[active] = np.clip(hazard[active] * (1.0 - DELTA), EPS, 1.0 - EPS)
    clock_mech = mechanism_respects_clock(test, hazard, model)
    if not clock_mech["action_unchanged"] or not clock_mech["outside_unchanged"]:
        raise RuntimeError(f"mecanismo do braço {arm} alterou a hazard fora da resposta")
    from .science import survival_at_18

    base = survival_at_18(test, hazard)
    shock_s = survival_at_18(test, shock)
    mech_s = survival_at_18(test, clock_mech["mech"])
    both = base.merge(shock_s[KEYS + ["S"]], on=KEYS, suffixes=("_base", "_shock"))
    both = both.merge(mech_s[KEYS + ["S"]].rename(columns={"S": "S_mech"}), on=KEYS)
    both["dS_shock"] = both["S_shock"] - both["S_base"]
    both["dS_mech"] = both["S_mech"] - both["S_base"]
    both["female"] = both["gender"].astype(str).eq("F")
    contrasts = policy_contrasts(both)
    trigger_ids = set(map(tuple, test.loc[active, KEYS].drop_duplicates().itertuples(index=False, name=None)))
    r18_ids = set(map(tuple, r18_keys.itertuples(index=False, name=None)))
    response_ids = set(map(tuple, test.loc[clock_mech["response"], KEYS].drop_duplicates().itertuples(index=False, name=None)))
    cells = [
        _cell("n_teste", arm, int(keys.shape[0]), "matrícula"),
        _cell("n_linhas_teste", arm, int(len(test)), "linha"),
        _cell("n_eventos_teste", arm, int(y.sum()), "linha de evento"),
        _cell("auc_semanal", arm, float(weekly["auc"]), "linha de teste", ci=(weekly["ci_lo"], weekly["ci_hi"])),
        _cell("brier", arm, float(brier(y, p)), "linha de teste"),
        _cell("ece15", arm, ece, "linha de teste"),
        _cell("landmark_em_risco", arm, int(landmark["n_cases"] + landmark["n_controls"] + landmark["n_excluded"]), "matrícula"),
        _cell("landmark_casos", arm, int(landmark["n_cases"]), "matrícula"),
        _cell("landmark_controles", arm, int(landmark["n_controls"]), "matrícula"),
        _cell("landmark_excluidos", arm, int(landmark["n_excluded"]), "matrícula"),
        _cell("auc_landmark", arm, landmark["auc_unweighted"], "caso e controle", landmark_status if landmark["auc_unweighted"] is None else "computed", ci=None if landmark["auc_unweighted_ci"] is None else tuple(landmark["auc_unweighted_ci"])),
        _cell("auc_ipcw", arm, None if landmark_status == "NO-GO" else landmark["auc"], "caso e controle", landmark_status, ci=None if landmark_status == "NO-GO" or landmark["auc_ci"] is None else tuple(landmark["auc_ci"])),
        _cell("G18", arm, None if landmark_status == "NO-GO" else g18, "treino em risco na semana 8", landmark_status),
        _cell("ess_casos", arm, landmark["ess_cases"], "caso"),
        _cell("ess_controles", arm, landmark["ess_controls"], "controle"),
        _cell("r18", arm, int(len(r18_keys)), "matrícula de teste no painel"),
        _cell("gatilho_r18", arm, int(len(trigger_ids & r18_ids)), "R18 do próprio braço"),
        _cell("resposta_r18", arm, int(len(response_ids & r18_ids)), "R18 do próprio braço"),
        _cell("delta_s_choque", arm, contrasts["delta_s_shock"], "R18 do próprio braço", ci=None if contrasts["delta_s_shock_ci"] is None else tuple(contrasts["delta_s_shock_ci"])),
        _cell("delta_s_mecanismo", arm, contrasts["delta_s_mechanism"], "R18 do próprio braço", ci=None if contrasts["delta_s_mechanism_ci"] is None else tuple(contrasts["delta_s_mechanism_ci"])),
        _cell("gap_basal", arm, float(both.loc[both["female"], "S_base"].mean() - both.loc[~both["female"], "S_base"].mean()), "R18 do próprio braço"),
        _cell("gap_choque", arm, float(both.loc[both["female"], "S_shock"].mean() - both.loc[~both["female"], "S_shock"].mean()), "R18 do próprio braço"),
        _cell("delta_gap_choque", arm, contrasts["delta_gap_shock"], "R18 do próprio braço", ci=None if contrasts["delta_gap_shock_ci"] is None else tuple(contrasts["delta_gap_shock_ci"])),
        _cell("gap_mecanismo", arm, float(both.loc[both["female"], "S_mech"].mean() - both.loc[~both["female"], "S_mech"].mean()), "R18 do próprio braço"),
        _cell("delta_gap_mecanismo", arm, contrasts["delta_gap_mechanism"], "R18 do próprio braço", ci=None if contrasts["delta_gap_mechanism_ci"] is None else tuple(contrasts["delta_gap_mechanism_ci"])),
    ]
    if (arm, "gatilho_f") not in UNAVAILABLE:
        r18_gender = test.loc[test["week"] == 18, KEYS + ["gender"]].drop_duplicates()
        triggered = test.loc[active, KEYS].drop_duplicates()
        gendered = r18_gender.merge(triggered, on=KEYS, how="inner")
        sex = gendered["gender"].astype(str)
        cells.append(_cell("gatilho_f", arm, int(sex.eq("F").sum()), "R18 feminino"))
        cells.append(_cell("gatilho_m", arm, int(sex.eq("M").sum()), "R18 masculino"))
    if (arm, "linhas_sem_registro") not in UNAVAILABLE:
        cells.append(_cell("linhas_sem_registro", arm, int(((test["absent_record"] == 1)).sum()), "linha"))
    if (arm, "clique_zero") not in UNAVAILABLE:
        cells.append(_cell("clique_zero", arm, int(((test["click_record"] == 1) & (test["total_clicks"] == 0)).sum()), "linha"))
    if (arm, "semana_nominal_parcial") not in UNAVAILABLE:
        cells.append(_cell("semana_nominal_parcial", arm, int((test["partial_nominal_week"] == 1).sum()), "linha"))
    payload = {
        "arm": arm,
        "cells": cells,
        "contrasts": contrasts,
        "bootstrap": _bootstrap_rows(both, arm),
        "landmark_status": landmark_status,
        "frozen_ok": bool(landmark["frozen_ok"]),
        "G18": g18,
    }
    (output / "results").mkdir(parents=True, exist_ok=True)
    (output / "results" / f"{arm}.json").write_text(json.dumps(payload), encoding="utf-8")
    return {"test_keys": test[KEYS + ["week", "event", "hazard_hat"]], "payload": payload}


def run_approved(raw: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    enrollments, test_ids, clicks, submitted = _prepare(raw)
    saved = {}
    for arm in ("A", "B", "B-9"):
        print(f"arm {arm} start", flush=True)
        frame = build_frame(enrollments, clicks, submitted, test_ids, arm)
        saved[arm] = score_arm(frame, enrollments, test_ids, arm, output)
        del frame
        print(f"arm {arm} done", flush=True)
    _common_support(saved["A"]["test_keys"], saved["B"]["test_keys"], output)
    rows = []
    for arm in saved:
        payload = json.loads((output / "results" / f"{arm}.json").read_text(encoding="utf-8"))
        rows.extend(payload["bootstrap"])
    (output / "results" / "bootstrap.json").write_text(json.dumps(rows), encoding="utf-8")
    return {"arms": list(saved), "output": str(output)}


def _common_support(left: pd.DataFrame, right: pd.DataFrame, output: Path) -> None:
    keys = KEYS + ["week"]
    merged = left.merge(right, on=keys, suffixes=("_a", "_b"))
    rows = int(len(merged))
    def _auc_brier(frame: pd.DataFrame, event: str, score: str) -> tuple[float | None, float | None, tuple | None]:
        if frame.empty or frame[event].nunique() < 2:
            return None, None, None
        scored = frame[["id_student", event, score]].rename(columns={event: "event", score: "hazard_hat"})
        auc = clustered_auc(scored)
        return float(auc["auc"]), float(brier(scored["event"].to_numpy(dtype=int), scored["hazard_hat"].to_numpy(dtype=float))), (auc["ci_lo"], auc["ci_hi"])

    auc_a, brier_a, ci_a = _auc_brier(merged, "event_a", "hazard_hat_a")
    auc_b, brier_b, ci_b = _auc_brier(merged, "event_b", "hazard_hat_b")
    extra = {
        "A": [_cell("suporte_comum_linhas", "A", rows, "linha comum"), _cell("auc_suporte_comum", "A", auc_a, "linha comum", ci=ci_a), _cell("brier_suporte_comum", "A", brier_a, "linha comum")],
        "B": [_cell("suporte_comum_linhas", "B", rows, "linha comum"), _cell("auc_suporte_comum", "B", auc_b, "linha comum", ci=ci_b), _cell("brier_suporte_comum", "B", brier_b, "linha comum")],
    }
    for arm, cells in extra.items():
        path = output / "results" / f"{arm}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cells"].extend(cells)
        path.write_text(json.dumps(payload), encoding="utf-8")
