from __future__ import annotations

import pandas as pd

from .landmark import cohort_frame
from .science import KEYS, STATICS, event_backbone, weekly_clicks, weekly_submissions
from .stage01_download import CSV_NAMES


def run(ctx) -> dict:
    missing = [name for name in CSV_NAMES if not (ctx.raw / name).exists()]
    if missing:
        return {"status": "NOT_RUN_SCIENCE", "message": f"coorte não construída; faltam {missing}"}
    enr = event_backbone(ctx.raw)
    info = pd.read_csv(ctx.raw / "studentInfo.csv", usecols=KEYS + STATICS)
    enr = enr.merge(info, on=KEYS, how="left", validate="1:1")
    if len(enr) != 32593:
        return {"status": "FAIL", "message": f"matrículas {len(enr)} != 32593"}
    try:
        frame = cohort_frame(enr, weekly_clicks(ctx.raw), weekly_submissions(ctx.raw))
    except RuntimeError as exc:
        return {"status": "FAIL", "message": str(exc)}
    ctx.processed.mkdir(parents=True, exist_ok=True)
    enr.to_csv(ctx.processed / "enrollments.csv", index=False)
    frame.to_csv(ctx.processed / "person_period.csv", index=False)
    return {"status": "PASS", "message": f"painel com {len(frame)} linhas", "n_enrollments": int(len(enr))}
