from __future__ import annotations

import json

import joblib
import pandas as pd

from .audit import SCORE_COLUMNS, assert_score_contract
from .landmark import evaluate_landmark
from .science import FEATURES, KEYS, STATICS, attach_s_star, brier, clustered_auc, ece15, fit_one


def run(ctx) -> dict:
    frame_path = ctx.processed / "person_period_split.csv"
    if not frame_path.exists():
        return {"status": "NOT_RUN_SCIENCE", "message": "ajuste não executado; person_period_split.csv ausente"}
    frame = pd.read_csv(frame_path)
    if "split" not in frame.columns:
        return {"status": "FAIL", "message": "painel sem coluna split"}
    train = frame.loc[frame["split"] == "train"].copy()
    test = frame.loc[frame["split"] == "test"].copy()
    model = fit_one(train)
    ctx.models.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ctx.models / "hazard.joblib")
    test = attach_s_star(test.copy())
    test["hazard_hat"] = model.predict_proba(test[FEATURES])[:, 1]
    assert_score_contract(test)
    y = test["event"].to_numpy(dtype=int)
    p = test["hazard_hat"].to_numpy(dtype=float)
    weekly = clustered_auc(test)
    metrics = {
        "n_rows": int(len(test)),
        "n_test_rows": int(len(test)),
        "n_event_rows": int(y.sum()),
        "auc_student_bootstrap": weekly,
        "weekly_auc_4dp": weekly["auc"],
        "brier": brier(y, p),
        "weekly_brier_6dp": brier(y, p),
        "ece15": ece15(y, p),
        "static_columns": STATICS,
    }
    ctx.results.mkdir(parents=True, exist_ok=True)
    (ctx.results / "p2_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    private = ctx.results / "private"
    private.mkdir(parents=True, exist_ok=True)
    test[SCORE_COLUMNS].to_csv(private / "pp_test_scores.csv", index=False)
    enroll_path = ctx.processed / "enrollments.csv"
    train_path = ctx.processed / "enroll_train_keys.csv"
    if not enroll_path.exists() or not train_path.exists():
        return {"status": "FAIL", "message": "marco não calculado; faltam matrículas ou chaves de treino"}
    enr = pd.read_csv(enroll_path)
    train_ids = set(pd.read_csv(train_path)["id_student"])
    try:
        report = evaluate_landmark(enr, frame, model, train_ids, require_frozen=True)
    except RuntimeError as exc:
        return {"status": "FAIL", "message": str(exc)}
    if report.get("auc") is None or not report["frozen_ok"]:
        return {"status": "FAIL", "message": f"marco fora de 576/6275/435 ou sem AUC: {report['n_cases']}/{report['n_controls']}/{report['n_excluded']}"}
    landmark_payload = {key: report[key] for key in ("n_cases", "n_controls", "n_excluded", "G18", "auc", "auc_ci", "auc_unweighted", "ess_cases", "ess_controls", "support", "n_without_week9", "snapshot_gap", "population")}
    landmark_payload["landmark_ipcw_auc_4dp"] = report["auc"]
    landmark_payload["landmark_unweighted_auc_4dp"] = report["auc_unweighted"]
    (ctx.results / "landmark.json").write_text(json.dumps(landmark_payload), encoding="utf-8")
    bins = [row for row in metrics["ece15"] if "bin" in row]
    pd.DataFrame(bins).to_csv(ctx.curves / "calibration_bins.csv", index=False)
    return {"status": "PASS", "message": "ajuste e contrato de colunas; contagens do marco sem identificador"}
