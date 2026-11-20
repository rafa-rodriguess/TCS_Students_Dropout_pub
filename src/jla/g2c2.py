"""Relógio A/B/B−9 para a reprodução G2c.2.

Este módulo não treina, não baixa OULAD e não lê alvos numéricos para
produzir escores. A máscara dos nove Fail com data de saída conflitante
precisa ser explícita: o contrato público não define o predicado.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .science import (
    ALPHA_FIRST,
    ALPHA_SECOND,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    CATEGORICAL,
    DELTA,
    FEATURES,
    FORBIDDEN,
    KEYS,
    NUMERIC,
    add_lag,
    add_same_week_state,
    assert_lag,
    expand,
)

ARMS = ("A", "B", "B-9")
NOMINAL_RESULTS = frozenset({"pass", "fail", "distinction"})
LEAKAGE = frozenset(FORBIDDEN) | {"date_registration"}
UNAVAILABLE_CELLS = (
    ("linhas_sem_registro", "A", "definição não está no resumo congelado"),
    ("clique_zero", "A", "definição não está no resumo congelado"),
    ("semana_nominal_parcial", "A", "A não abre a semana nominal"),
    ("suporte_comum_linhas", "B-9", "B-9 não foi juntado aos escores A"),
    ("auc_suporte_comum", "B-9", "B-9 não foi juntado aos escores A"),
    ("brier_suporte_comum", "B-9", "B-9 não foi juntado aos escores A"),
    ("gatilho_f", "A", "o resumo congelado não separa o gatilho por sexo"),
    ("gatilho_m", "A", "o resumo congelado não separa o gatilho por sexo"),
)
CATALOG_FIELDS = ("indicator", "arm", "estimand", "denominator", "status", "reason")
BOOTSTRAP_FIELDS = ("arm", "estimand", "draws", "seed", "unit", "model", "status")
SCHEDULED_COUNTS = {
    "cohort_enrollments": 32593,
    "train_enrollments": 22855,
    "test_enrollments_a": 9738,
    "test_rows_a": 232509,
    "r18_a": 6369,
    "test_rows_b": 278056,
    "r18_b": 7337,
    "test_rows_b9": 277979,
    "test_enrollments_b9": 9736,
    "r18_b9": 7335,
}


class MethodStop(RuntimeError):
    """Dependência metodológica que o contrato público não fecha."""


class FitForbidden(RuntimeError):
    """R0 não autoriza ajuste, calibração real nem escores."""


def model_specification() -> dict:
    return {
        "solver": "liblinear",
        "C": 1.0,
        "max_iter": 4000,
        "class_weight": "balanced",
        "random_state": 42,
        "calibration": "sigmoid",
        "ensemble": False,
        "cv": "GroupKFold_splits_by_id_student",
        "n_splits": 5,
        "cv_integer_forbidden": True,
        "features": list(FEATURES),
        "numeric": list(NUMERIC),
        "categorical": list(CATEGORICAL),
        "leakage": sorted(LEAKAGE),
        "delta": DELTA,
        "alpha_first": ALPHA_FIRST,
        "alpha_second": ALPHA_SECOND,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_unit": "id_student",
        "estimator": "fixed",
        "fit": "forbidden_in_r0",
    }


def refuse_fit(*_args, **_kwargs):
    raise FitForbidden("R0 proíbe fit, calibração real, download e escores novos")


def student_group_splits(frame: pd.DataFrame, n_splits: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    from sklearn.model_selection import GroupKFold

    groups = frame["id_student"].to_numpy()
    y = frame["event"].astype(int).to_numpy()
    splits = list(GroupKFold(n_splits=n_splits).split(frame, y, groups))
    for train, test in splits:
        if set(groups[train]) & set(groups[test]):
            raise MethodStop("estudante de teste dentro do treino")
    return splits


def nominal_week(length: float) -> int:
    number = float(length)
    if not math.isfinite(number) or number < 0:
        raise MethodStop("comprimento de apresentação inválido; sem imputação")
    return int(math.floor(number / 7.0))


def partial_nominal(length: float) -> bool:
    number = float(length)
    if not math.isfinite(number) or number < 0:
        raise MethodStop("comprimento de apresentação inválido; sem imputação")
    return (number % 7.0) != 0.0


def _result(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower()


def _date(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def clock_frame(enrollments: pd.DataFrame, arm: str, conflict: pd.Series | None = None) -> pd.DataFrame:
    """Monta o fim do acompanhamento. Não lê arquivos e não estima métricas."""
    if arm not in ARMS:
        raise MethodStop(f"braço desconhecido: {arm}")
    required = KEYS + ["final_result", "date_unregistration", "t_last_obs_week", "module_presentation_length"]
    missing = [column for column in required if column not in enrollments.columns]
    if missing:
        raise MethodStop("matrícula sem " + ", ".join(missing))
    work = enrollments.copy().reset_index(drop=True)
    if arm == "B-9":
        if conflict is None:
            raise MethodStop(
                "B-9 exige máscara explícita dos Fail com data de saída conflitante; "
                "o predicado não está no contrato público"
            )
        mask = conflict.astype(bool).to_numpy()
        if len(mask) != len(work):
            raise MethodStop("máscara de conflito com comprimento diferente da coorte")
        work = work.loc[~mask].reset_index(drop=True)
        conflict_flag = np.zeros(len(work), dtype=int)
    else:
        conflict_flag = np.zeros(len(work), dtype=int)
        if arm == "B" and conflict is not None:
            mask = conflict.astype(bool).to_numpy()
            if len(mask) != len(enrollments):
                raise MethodStop("máscara de conflito com comprimento diferente da coorte")
            conflict_flag = mask.astype(int)
    result = _result(work["final_result"])
    date = _date(work["date_unregistration"])
    last = pd.to_numeric(work["t_last_obs_week"], errors="coerce").fillna(0).astype(int).clip(lower=0)
    event = result.eq("withdrawn") & date.notna() & date.ge(0)
    t_event = np.floor(date.to_numpy(dtype=float) / 7.0)
    t_event = pd.Series(t_event, index=work.index).where(event)
    ends = np.zeros(len(work), dtype=int)
    reason = np.array([""] * len(work), dtype=object)
    length = pd.to_numeric(work["module_presentation_length"], errors="coerce")
    for i in range(len(work)):
        if bool(event.iloc[i]):
            ends[i] = max(int(t_event.iloc[i]), 0)
            reason[i] = "event"
            continue
        if result.iloc[i] == "withdrawn":
            ends[i] = int(last.iloc[i])
            reason[i] = "withdrawn_without_v6_event"
            continue
        if result.iloc[i] not in NOMINAL_RESULTS:
            raise MethodStop("desfecho fora de Withdrawn/Pass/Fail/Distinction")
        if arm == "A":
            ends[i] = int(last.iloc[i])
            reason[i] = "last_vle"
            continue
        if pd.isna(length.iloc[i]):
            raise MethodStop("apresentação sem comprimento; sem imputação")
        ends[i] = nominal_week(float(length.iloc[i]))
        reason[i] = "nominal"
        observed = int(last.iloc[i])
        if observed > ends[i]:
            ends[i] = observed
            reason[i] = "nominal_plus_observed"
    out = work[KEYS].copy()
    out["event_withdrawn"] = event.astype(int).to_numpy()
    out["t_event_week"] = t_event.to_numpy()
    out["t_last_obs_week"] = last.to_numpy(dtype=int)
    out["t_final_week"] = ends
    out["time_for_split"] = ends
    out["clock_reason"] = reason
    out["conflict_fail"] = conflict_flag
    out["module_presentation_length"] = length.to_numpy()
    out["arm"] = arm
    return out


def mark_partial(frame: pd.DataFrame, clock: pd.DataFrame) -> pd.DataFrame:
    del clock
    out = frame.copy()
    partial = np.zeros(len(out), dtype=int)
    length = pd.to_numeric(out["module_presentation_length"], errors="coerce")
    nominal_row = out["clock_reason"].isin(["nominal", "nominal_plus_observed"]) & out["arm"].isin(["B", "B-9"])
    for i in np.flatnonzero(nominal_row.to_numpy()):
        if pd.isna(length.iloc[i]):
            continue
        week = nominal_week(float(length.iloc[i]))
        if partial_nominal(float(length.iloc[i])) and int(out["week"].iloc[i]) == week:
            partial[i] = 1
    out["partial_nominal_week"] = partial
    return out


def with_activity(frame: pd.DataFrame, clicks: pd.DataFrame, submitted: pd.DataFrame) -> pd.DataFrame:
    keys = KEYS + ["week"]
    seen = pd.concat(
        [clicks[keys].assign(_seen=1), submitted[keys].assign(_seen=1)],
        ignore_index=True,
    ).drop_duplicates(keys)
    out = add_same_week_state(frame, clicks, submitted)
    out = out.merge(seen, on=keys, how="left", validate="m:1")
    out["absent_record"] = out["_seen"].isna().astype(int)
    return add_lag(out.drop(columns=["_seen"]))


def assert_previous_week_lag(frame: pd.DataFrame) -> None:
    assert_lag(frame)
    if set(FEATURES) & LEAKAGE:
        raise RuntimeError("vazamento na whitelist")
    ordered = frame.sort_values(KEYS + ["week"]).reset_index(drop=True)
    previous = ordered.groupby(KEYS, sort=False)["total_clicks"].shift(1)
    later = ordered["week"].to_numpy(dtype=int) > 0
    if later.any() and not np.allclose(ordered.loc[later, "total_clicks_lag"].to_numpy(dtype=float), previous.loc[later].to_numpy(dtype=float)):
        raise RuntimeError("lag não copia o clique da semana anterior")
    week0 = ordered["week"].eq(0)
    if int((week0 & ordered["lag_available"].ne(0)).sum()):
        raise RuntimeError("semana zero com lag")


def panel(enrollments: pd.DataFrame, clicks: pd.DataFrame, submitted: pd.DataFrame, arm: str, conflict: pd.Series | None = None) -> pd.DataFrame:
    clock = clock_frame(enrollments, arm, conflict)
    expanded = expand(clock)
    expanded = mark_partial(expanded, clock)
    out = with_activity(expanded, clicks, submitted)
    assert_previous_week_lag(out)
    return out


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def indicator_catalog(path: Path) -> dict:
    rows = _read_rows(path)
    if len(rows) != 99:
        raise MethodStop(f"catálogo de indicadores tem {len(rows)} linhas; o contrato exige 99")
    public = [{field: row[field] for field in CATALOG_FIELDS} for row in rows]
    found = {(row["indicator"], row["arm"], row["reason"]) for row in public if row["status"] == "UNAVAILABLE"}
    expected = set(UNAVAILABLE_CELLS)
    if found != expected:
        raise MethodStop("as oito células UNAVAILABLE não conferem com o contrato publicado")
    if any(row["value"] for row in rows if row["status"] == "UNAVAILABLE"):
        raise MethodStop("célula UNAVAILABLE com valor preenchido")
    return {"n": 99, "unavailable": 8, "scheduled": 91, "rows": public}


def bootstrap_catalog(path: Path) -> dict:
    rows = _read_rows(path)
    if len(rows) != 12:
        raise MethodStop(f"catálogo de bootstrap tem {len(rows)} linhas; o contrato exige 12")
    public = []
    for row in rows:
        if row["draws"] != "500" or row["seed"] != "42" or row["unit"] != "id_student" or row["model"] != "fixed":
            raise MethodStop("contraste fora de 500 draws, seed 42, id_student e estimador fixo")
        public.append({field: row[field] for field in BOOTSTRAP_FIELDS})
    return {"n": 12, "rows": public}


def preflight_decision() -> dict:
    return {
        "r0_isolated_code": "GO",
        "r1_execution": "NO-GO",
        "g2c2_numeric_pass": "NO-GO",
        "decision": "STOP",
        "obstacles": [
            "O predicado que identifica os nove Fail com data de saída conflitante não está no contrato público.",
            "A enumeração privada B01–B16 não está neste repositório e não foi importada.",
            "O runner A6 não constrói a grade nominal B nem B−9; o resultado A6 não autoriza PASS G2c.2.",
            "courses.csv, vle.csv e o ZIP seguem PENDING no protocolo; a equivalência semântica não substitui o hash bruto.",
        ],
    }
