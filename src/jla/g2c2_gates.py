"""Gates estruturais da R1, antes de qualquer ajuste.

Conta matrículas, split, Fail9 e linhas de risco. Não treina e não grava escores.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .g2c2 import clock_frame, fail9_mask
from .science import KEYS, student_disjoint_split

EXPECTED = {
    "n_enrollments": 32593,
    "n_presentations": 22,
    "n_train_enrollments": 22855,
    "n_test_enrollments": 9738,
    "student_overlap": 0,
    "fail9": 9,
    "fail9_negative": 2,
    "fail9_zero": 6,
    "fail9_positive": 1,
    "fail9_train": 7,
    "fail9_test": 2,
    "rows_a": 775295,
    "rows_b": 928604,
    "rows_b_minus_a": 153309,
    "rows_b_test": 278056,
    "rows_b9_test": 277979,
    "r18_a": 6369,
    "r18_b": 7337,
    "r18_b9": 7335,
}


def structural_report(observed: dict) -> dict:
    mismatches = []
    for key, expected in EXPECTED.items():
        if observed.get(key) != expected:
            mismatches.append({"gate": key, "expected": expected, "observed": observed.get(key)})
    return {"status": "PASS" if not mismatches else "STOP", "mismatches": mismatches, "observed": observed}


def _last_week(raw: Path) -> pd.DataFrame:
    vle = pd.read_csv(raw / "studentVle.csv", usecols=KEYS + ["date"])
    vle["date"] = pd.to_numeric(vle["date"], errors="coerce")
    vle = vle.loc[vle["date"].notna() & (vle["date"] >= 0), KEYS + ["date"]]
    vle["week"] = np.floor(vle["date"].to_numpy(dtype=float) / 7.0).astype(int)
    vle.loc[vle["week"] < 0, "week"] = 0
    return vle.groupby(KEYS, sort=False)["week"].max().rename("t_last_obs_week").reset_index()


def load_enrollments(raw: Path) -> tuple[pd.DataFrame, int]:
    info = pd.read_csv(raw / "studentInfo.csv", usecols=KEYS + ["final_result"])
    reg = pd.read_csv(raw / "studentRegistration.csv", usecols=KEYS + ["date_unregistration"])
    courses = pd.read_csv(raw / "courses.csv", usecols=["code_module", "code_presentation", "module_presentation_length"])
    enrollments = info.merge(reg, on=KEYS, how="left").drop_duplicates(subset=KEYS).reset_index(drop=True)
    enrollments = enrollments.merge(courses, on=["code_module", "code_presentation"], how="left", validate="m:1")
    enrollments = enrollments.merge(_last_week(raw), on=KEYS, how="left")
    enrollments["t_last_obs_week"] = enrollments["t_last_obs_week"].fillna(0).astype(int)
    return enrollments, int(courses.drop_duplicates(["code_module", "code_presentation"]).shape[0])


def _rows(clock: pd.DataFrame) -> int:
    if (clock["t_final_week"] < 0).any():
        raise RuntimeError("acompanhamento negativo")
    return int((clock["t_final_week"].astype(int) + 1).sum())


def measure(raw: Path) -> dict:
    enrollments, presentations = load_enrollments(raw)
    clock_a = clock_frame(enrollments, "A")
    is_test, _strata = student_disjoint_split(clock_a)
    test_ids = set(clock_a.loc[is_test.to_numpy(), "id_student"])
    train_ids = set(clock_a.loc[~is_test.to_numpy(), "id_student"])
    clock_b = clock_frame(enrollments, "B")
    clock_b9 = clock_frame(enrollments, "B-9")
    date = pd.to_numeric(enrollments["date_unregistration"], errors="coerce")
    mask = fail9_mask(enrollments)
    fail_students = enrollments.loc[mask.to_numpy(), "id_student"]
    b_test = clock_b["id_student"].isin(test_ids)
    b9_test = clock_b9["id_student"].isin(test_ids)
    a_test = clock_a["id_student"].isin(test_ids)
    return {
        "n_enrollments": int(len(enrollments)),
        "n_presentations": presentations,
        "n_train_enrollments": int((~is_test).sum()),
        "n_test_enrollments": int(is_test.sum()),
        "student_overlap": int(len(train_ids & test_ids)),
        "fail9": int(mask.sum()),
        "fail9_negative": int((mask & date.lt(0)).sum()),
        "fail9_zero": int((mask & date.eq(0)).sum()),
        "fail9_positive": int((mask & date.gt(0)).sum()),
        "fail9_train": int(fail_students.isin(train_ids).sum()),
        "fail9_test": int(fail_students.isin(test_ids).sum()),
        "rows_a": _rows(clock_a),
        "rows_b": _rows(clock_b),
        "rows_b_minus_a": _rows(clock_b) - _rows(clock_a),
        "rows_b_test": _rows(clock_b.loc[b_test]),
        "rows_b9_test": _rows(clock_b9.loc[b9_test]),
        "r18_a": int((a_test & clock_a["t_final_week"].ge(18)).sum()),
        "r18_b": int((b_test & clock_b["t_final_week"].ge(18)).sum()),
        "r18_b9": int((b9_test & clock_b9["t_final_week"].ge(18)).sum()),
    }
