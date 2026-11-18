from __future__ import annotations

import json

import pandas as pd

from .science import KEYS, event_backbone, student_disjoint_split


def run(ctx) -> dict:
    if not (ctx.raw / "studentInfo.csv").exists():
        return {"status": "NOT_RUN_SCIENCE", "message": "split não executado; OULAD ausente"}
    enr = event_backbone(ctx.raw)
    is_test, strata = student_disjoint_split(enr)
    train_ids = set(enr.loc[~is_test, "id_student"])
    test_ids = set(enr.loc[is_test, "id_student"])
    if train_ids & test_ids:
        return {"status": "FAIL", "message": "overlap de estudante não é zero"}
    ctx.processed.mkdir(parents=True, exist_ok=True)
    ctx.results.mkdir(parents=True, exist_ok=True)
    enr.loc[~is_test, KEYS].to_csv(ctx.processed / "enroll_train_keys.csv", index=False)
    enr.loc[is_test, KEYS].to_csv(ctx.processed / "enroll_test_keys.csv", index=False)
    frame_path = ctx.processed / "person_period.csv"
    if frame_path.exists():
        frame = pd.read_csv(frame_path)
        test_keys = enr.loc[is_test, KEYS].assign(_t=1)
        marked = frame.merge(test_keys, on=KEYS, how="left")
        marked["split"] = marked["_t"].eq(1).map({True: "test", False: "train"})
        marked.drop(columns="_t").to_csv(ctx.processed / "person_period_split.csv", index=False)
    strata.to_csv(ctx.results / "split_strata.csv", index=False)
    payload = {
        "n_enrollments": int(len(enr)),
        "n_students": int(enr["id_student"].nunique()),
        "n_events": int(enr["event_withdrawn"].sum()),
        "n_test_students": int(len(test_ids)),
        "n_test_enrollments": int(is_test.sum()),
        "n_test_events": int(enr.loc[is_test, "event_withdrawn"].sum()),
        "overlap_students": 0,
    }
    (ctx.results / "p1_metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    return {
        "status": "PASS",
        "message": "split por estudante",
        "n_test_students": int(len(test_ids)),
        "n_test_enrollments": int(is_test.sum()),
        "n_test_events": int(enr.loc[is_test, "event_withdrawn"].sum()),
    }
