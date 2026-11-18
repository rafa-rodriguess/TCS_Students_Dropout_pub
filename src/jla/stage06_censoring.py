from __future__ import annotations

import json

import pandas as pd

from .audit import landmark_roles
from .landmark import g_from_train_at_risk


def run(ctx) -> dict:
    path = ctx.processed / "enrollments.csv"
    keys = ctx.processed / "enroll_train_keys.csv"
    if not path.exists() or not keys.exists():
        return {"status": "NOT_RUN_SCIENCE", "message": "censura não calculada; faltam matrículas ou chaves de treino"}
    enr = pd.read_csv(path)
    train_ids = set(pd.read_csv(keys)["id_student"])
    try:
        g = g_from_train_at_risk(enr, train_ids)
    except RuntimeError as exc:
        return {"status": "FAIL", "message": str(exc)}
    ctx.curves.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"week": list(g), "g": list(g.values())}).to_csv(ctx.curves / "censoring_g.csv", index=False)
    train = enr.loc[enr["id_student"].isin(train_ids)]
    n_at_risk = int(landmark_roles(train)["at_risk"].sum())
    payload = {"G18": g.get(18), "g18_4dp": g.get(18), "population": "train_at_risk_at_L", "n_at_risk": n_at_risk}
    (ctx.results / "censoring.json").write_text(json.dumps(payload), encoding="utf-8")
    return {"status": "PASS", "message": "G(t) só no treino em risco no marco; o teste não entra nessa curva"}
