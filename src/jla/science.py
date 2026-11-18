# Funções copiadas de p1, p2, p3 e a3, com diretório de entrada explícito.
# Importar este módulo não treina, não baixa e não lê ~/.ia_orchestrator.

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

KEYS = ["id_student", "code_module", "code_presentation"]
NUMERIC = [
    "lag_available",
    "total_clicks_lag",
    "studied_credits",
    "num_of_prev_attempts",
    "recency_lag",
    "streak_lag",
    "submitted_lag",
]
CATEGORICAL = [
    "week",
    "code_module",
    "code_presentation",
    "highest_education",
    "age_band",
    "gender",
]
STATICS = [
    "studied_credits",
    "num_of_prev_attempts",
    "highest_education",
    "age_band",
    "gender",
]
FEATURES = NUMERIC + CATEGORICAL
FORBIDDEN = {
    "event",
    "event_withdrawn",
    "t_event_week",
    "t_final_week",
    "t_last_obs_week",
    "time_for_split",
    "final_result",
    "date_unregistration",
    "total_clicks",
    "recency",
    "streak",
    "submitted_this_week",
}
EPS = 1e-12
DELTA = 0.08
ALPHA_FIRST = 0.35
ALPHA_SECOND = 0.10
BOOTSTRAP_DRAWS = 500
BOOTSTRAP_SEED = 42


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def event_backbone(raw: Path) -> pd.DataFrame:
    info = pd.read_csv(raw / "studentInfo.csv", usecols=KEYS + ["final_result"])
    reg = pd.read_csv(raw / "studentRegistration.csv", usecols=KEYS + ["date_unregistration"])
    enrollments = info.merge(reg, on=KEYS, how="left").drop_duplicates(subset=KEYS).reset_index(drop=True)
    date = pd.to_numeric(enrollments["date_unregistration"], errors="coerce").mask(lambda s: s < 0)
    withdrawn = enrollments["final_result"].astype(str).str.strip().str.lower().eq("withdrawn")
    event = (withdrawn & date.notna()).astype(int)
    t_event = pd.Series(np.floor(date / 7.0), index=enrollments.index).where(event.eq(1))
    vle = pd.read_csv(raw / "studentVle.csv", usecols=KEYS + ["date"])
    vle["date"] = pd.to_numeric(vle["date"], errors="coerce")
    vle = vle.loc[vle["date"].notna() & (vle["date"] >= 0), KEYS + ["date"]]
    vle["week"] = np.floor(vle["date"].to_numpy(dtype=float) / 7.0).astype(int)
    vle.loc[vle["week"] < 0, "week"] = 0
    last = vle.groupby(KEYS, sort=False)["week"].max()
    out = enrollments[KEYS].copy()
    out["event_withdrawn"] = event.to_numpy(dtype=int)
    out["t_event_week"] = t_event.to_numpy()
    out = out.merge(last.rename("t_last_obs_week"), on=KEYS, how="left")
    out["t_last_obs_week"] = out["t_last_obs_week"].fillna(0).astype(int)
    t_final = out["t_last_obs_week"].to_numpy(dtype=int).copy()
    event_mask = out["event_withdrawn"].to_numpy(dtype=bool)
    t_final[event_mask] = out.loc[event_mask, "t_event_week"].astype(int).to_numpy()
    t_final[t_final < 0] = 0
    out["t_final_week"] = t_final.astype(int)
    out["time_for_split"] = out["t_final_week"].to_numpy(dtype=int).copy()
    return out


def student_disjoint_split(enr: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(42)
    students = (
        enr.groupby("id_student")
        .agg(any_event=("event_withdrawn", "max"), time_med=("time_for_split", "median"))
        .reset_index()
    )
    students["time_bucket"] = pd.qcut(students["time_med"], q=4, labels=False, duplicates="drop")
    if students["time_bucket"].isna().any():
        raise RuntimeError("time quartile is missing; refusing to impute")
    students["stratum"] = students["any_event"].astype(int).astype(str) + "_B" + students["time_bucket"].astype(str)
    test_students: list[np.ndarray] = []
    rows = []
    for stratum, grp in students.groupby("stratum", sort=True):
        n = len(grp)
        n_test = 0 if n <= 1 else max(1, min(n - 1, int(round(0.30 * n))))
        if n_test:
            test_students.append(rng.choice(grp["id_student"].to_numpy(), size=n_test, replace=False))
        rows.append({"stratum": str(stratum), "n_students": int(n), "n_test_students": int(n_test)})
    test_ids = set(np.concatenate(test_students)) if test_students else set()
    return enr["id_student"].isin(test_ids), pd.DataFrame(rows)


def weekly_clicks(raw: Path) -> pd.DataFrame:
    vle = pd.read_csv(raw / "studentVle.csv", usecols=KEYS + ["date", "sum_click"])
    vle["date"] = pd.to_numeric(vle["date"], errors="coerce")
    vle["sum_click"] = pd.to_numeric(vle["sum_click"], errors="coerce").fillna(0.0)
    vle = vle.loc[vle["date"].notna() & (vle["date"] >= 0)]
    vle["week"] = np.floor(vle["date"].to_numpy(dtype=float) / 7.0).astype(int)
    vle.loc[vle["week"] < 0, "week"] = 0
    return vle.groupby(KEYS + ["week"], as_index=False)["sum_click"].sum().rename(columns={"sum_click": "total_clicks"})


def weekly_submissions(raw: Path) -> pd.DataFrame:
    submitted = pd.read_csv(raw / "studentAssessment.csv", usecols=["id_student", "id_assessment", "date_submitted"])
    assessments = pd.read_csv(raw / "assessments.csv", usecols=["id_assessment", "code_module", "code_presentation"])
    merged = submitted.merge(assessments, on="id_assessment", how="left", validate="m:1")
    merged["date_submitted"] = pd.to_numeric(merged["date_submitted"], errors="coerce")
    valid = merged["date_submitted"].notna() & (merged["date_submitted"] >= 0)
    valid &= merged["code_module"].notna() & merged["code_presentation"].notna()
    use = merged.loc[valid, KEYS + ["date_submitted"]].copy()
    use["week"] = np.floor(use["date_submitted"].to_numpy(dtype=float) / 7.0).astype(int)
    use.loc[use["week"] < 0, "week"] = 0
    return use.groupby(KEYS + ["week"], as_index=False).size().assign(submitted_this_week=1)[KEYS + ["week", "submitted_this_week"]]


def expand(enr: pd.DataFrame) -> pd.DataFrame:
    repeats = (enr["t_final_week"].to_numpy(dtype=int) + 1).astype(int)
    if (repeats <= 0).any():
        raise RuntimeError("non-positive follow-up")
    frame = enr.iloc[np.repeat(np.arange(len(enr)), repeats)].copy()
    frame["week"] = np.concatenate([np.arange(n, dtype=int) for n in repeats])
    t_event = pd.to_numeric(frame["t_event_week"], errors="coerce")
    frame["event"] = ((frame["event_withdrawn"].to_numpy(dtype=int) == 1) & (frame["week"].to_numpy() == t_event.to_numpy())).astype(int)
    return frame.reset_index(drop=True)


def add_same_week_state(frame: pd.DataFrame, clicks: pd.DataFrame, submitted: pd.DataFrame) -> pd.DataFrame:
    out = frame.merge(clicks, on=KEYS + ["week"], how="left", validate="m:1")
    out = out.merge(submitted, on=KEYS + ["week"], how="left", validate="m:1")
    out["total_clicks"] = out["total_clicks"].fillna(0.0)
    out["submitted_this_week"] = out["submitted_this_week"].fillna(0).astype(int)
    out = out.sort_values(KEYS + ["week"]).reset_index(drop=True)
    active = (out["total_clicks"].to_numpy(dtype=float) > 0).astype(int)
    keys = out[KEYS].astype(str).agg("|".join, axis=1).to_numpy()
    cuts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    recency = np.zeros(len(out), dtype=int)
    streak = np.zeros(len(out), dtype=int)
    ends = np.r_[cuts[1:], len(out)]
    for start, end in zip(cuts, ends):
        flags = active[start:end]
        r = np.zeros(end - start, dtype=int)
        s = np.zeros(end - start, dtype=int)
        for i, flag in enumerate(flags):
            if flag == 1:
                r[i] = 0
                s[i] = 1 if i == 0 else s[i - 1] + 1
            else:
                r[i] = 1 if i == 0 else r[i - 1] + 1
                s[i] = 0
        recency[start:end] = r
        streak[start:end] = s
    out["recency"] = recency
    out["streak"] = streak
    return out


def add_lag(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values(KEYS + ["week"]).reset_index(drop=True)
    grouped = out.groupby(KEYS, sort=False)
    out["total_clicks_lag"] = grouped["total_clicks"].shift(1)
    out["recency_lag"] = grouped["recency"].shift(1)
    out["streak_lag"] = grouped["streak"].shift(1)
    out["submitted_lag"] = grouped["submitted_this_week"].shift(1)
    out["lag_available"] = out["total_clicks_lag"].notna().astype(int)
    for column in ("total_clicks_lag", "recency_lag", "streak_lag", "submitted_lag"):
        out[column] = out[column].fillna(0.0)
    return out


def assert_lag(frame: pd.DataFrame) -> None:
    if set(FEATURES) & FORBIDDEN:
        raise RuntimeError("forbidden feature in the model matrix")
    week0 = frame["week"] == 0
    if int((week0 & (frame["lag_available"] != 0)).sum()):
        raise RuntimeError("week 0 has lagged history")


def fit_one(train: pd.DataFrame):
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(with_mean=True, with_std=True), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ],
        remainder="drop",
    )
    base = LogisticRegression(solver="liblinear", C=1.0, max_iter=4000, class_weight="balanced", random_state=42)
    pipe = Pipeline([("pre", pre), ("lr", base)])
    y = train["event"].astype(int).to_numpy()
    splits = list(GroupKFold(n_splits=5).split(train, y, train["id_student"].to_numpy()))
    model = CalibratedClassifierCV(estimator=pipe, method="sigmoid", cv=splits, ensemble=False)
    model.fit(train[FEATURES], y)
    return model


def ece15(y: np.ndarray, p: np.ndarray) -> list[dict]:
    bins = np.minimum((p * 15).astype(int), 14)
    rows = []
    for b in range(15):
        mask = bins == b
        n = int(mask.sum())
        rows.append({"bin": b, "lo": b / 15, "hi": (b + 1) / 15, "n": n, "mean_p": None if n == 0 else float(p[mask].mean()), "mean_y": None if n == 0 else float(y[mask].mean())})
    total = len(y)
    ece = float(sum((row["n"] / total) * abs(row["mean_p"] - row["mean_y"]) for row in rows if row["n"]))
    rows.append({"ece": ece})
    return rows


def clustered_auc(frame: pd.DataFrame, weight: np.ndarray | None = None, seed: int = 42, draws: int = 500) -> dict:
    frame = frame.reset_index(drop=True)
    y = frame["event"].to_numpy(dtype=int) if "event" in frame.columns else frame["y"].to_numpy(dtype=int)
    p = frame["hazard_hat"].to_numpy(dtype=float)
    positions = frame.groupby("id_student", sort=False).indices
    ids = np.array(list(positions))
    point = float(roc_auc_score(y, p, sample_weight=weight))
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(draws):
        chosen = rng.choice(len(ids), size=len(ids), replace=True)
        idx = np.concatenate([positions[ids[i]] for i in chosen])
        if y[idx].min() == y[idx].max():
            continue
        ww = None if weight is None else weight[idx]
        boots.append(float(roc_auc_score(y[idx], p[idx], sample_weight=ww)))
    arr = np.asarray(boots, dtype=float)
    if len(arr) < 50:
        return {"auc": point, "ci_lo": None, "ci_hi": None, "n_valid": int(len(arr)), "draws": draws}
    return {"auc": point, "ci_lo": float(np.quantile(arr, 0.025)), "ci_hi": float(np.quantile(arr, 0.975)), "n_valid": int(len(arr)), "draws": draws}


def censoring_g(enr: pd.DataFrame) -> dict[int, float]:
    event = enr["event_withdrawn"].to_numpy(dtype=int) == 1
    time = np.where(event, enr["t_event_week"].to_numpy(dtype=float), enr["t_final_week"].to_numpy(dtype=float))
    frame = pd.DataFrame({"time": time.astype(int), "cens": (~event).astype(int)})
    g_raw = {0: 1.0}
    survival = 1.0
    at_risk = len(frame)
    for week, grp in frame.groupby("time"):
        n_cens = int(grp["cens"].sum())
        if at_risk > 0 and n_cens > 0:
            survival *= 1.0 - n_cens / at_risk
        g_raw[int(week) + 1] = float(survival)
        at_risk -= len(grp)
    current = 1.0
    out = {}
    for week in range(0, max(int(frame["time"].max()) + 2, 40)):
        if week in g_raw:
            current = g_raw[week]
        out[week] = float(current)
    return out


def ess(weights: np.ndarray) -> float:
    if len(weights) == 0:
        return 0.0
    return float((weights.sum() ** 2) / np.square(weights).sum())


def clock_toy() -> dict:
    toy = pd.DataFrame(
        {"event_withdrawn": [0, 0, 0, 1], "t_event_week": [np.nan, np.nan, np.nan, 10], "t_final_week": [18, 18, 19, 10]}
    )
    g = censoring_g(toy)
    if not (g[18] == 1.0 and abs(g[19] - (1.0 / 3.0)) < 1e-12):
        raise RuntimeError(f"clock toy failed: G18={g[18]} G19={g[19]}")
    return {"G18": g[18], "G19": g[19]}


def active_from_recency(frame: pd.DataFrame) -> np.ndarray:
    hit = frame.loc[frame["recency"] >= 1, KEYS + ["week"]]
    s_star = hit.groupby(KEYS, as_index=False)["week"].min().rename(columns={"week": "s_star"})
    out = frame[KEYS + ["week"]].merge(s_star, on=KEYS, how="left")
    active = out["s_star"].notna() & out["week"].ge(out["s_star"] + 1) & out["week"].le(out["s_star"] + 2)
    return active.to_numpy(dtype=bool)


def toy_active_ignores_event() -> None:
    frame = pd.DataFrame(
        {
            "id_student": [1, 1, 1, 2, 2, 2],
            "code_module": ["AAA"] * 6,
            "code_presentation": ["2013J"] * 6,
            "week": [0, 1, 2, 0, 1, 2],
            "recency": [1, 0, 0, 1, 0, 0],
            "event": [0, 0, 0, 0, 1, 0],
        }
    )
    active = active_from_recency(frame)
    if not np.array_equal(active, np.array([False, True, True, False, True, True])):
        raise RuntimeError("event label changed the active window")


def survival_at_18(frame: pd.DataFrame, hazard: np.ndarray) -> pd.DataFrame:
    use = frame.loc[frame["week"] <= 18, KEYS + ["week", "gender"]].copy()
    use["h"] = np.clip(hazard[frame["week"].to_numpy() <= 18], EPS, 1.0 - EPS)
    use = use.sort_values(KEYS + ["week"])
    use["logS"] = np.log1p(-use["h"]).groupby([use[k] for k in KEYS], sort=False).cumsum()
    at = use.loc[use["week"] == 18, KEYS + ["gender", "logS"]].copy()
    at["S"] = np.exp(at["logS"])
    return at


def observed_week_table(frame: pd.DataFrame, hazard: np.ndarray) -> pd.DataFrame:
    use = frame.copy()
    use["h"] = np.clip(hazard, EPS, 1.0 - EPS)
    use = use.sort_values(KEYS + ["week"])
    grouped = [use[key] for key in KEYS]
    use["S"] = np.exp(np.log1p(-use["h"]).groupby(grouped, sort=False).cumsum())
    table = use.groupby("week", as_index=False).agg(n_enrollments=("S", "size"), mean_predicted_S_among_observed=("S", "mean"))
    table["interpretation"] = "descricao da sobrevida prevista entre matriculas observadas nesta semana"
    table["prohibition"] = "PROIBIDO usar como curva de sobrevivencia de coorte fixa"
    return table


def gap(values: np.ndarray, female: np.ndarray) -> float:
    return float(values[female].mean() - values[~female].mean())


def bootstrap(both: pd.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    positions = both.reset_index(drop=True).groupby("id_student", sort=False).indices
    ids = np.array(list(positions))
    table = both.reset_index(drop=True)
    contrast = table[column].to_numpy()
    base = table["S_base"].to_numpy()
    scenario = table["S_scenario"].to_numpy()
    female = table["female"].to_numpy()
    boot_s = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    boot_g = []
    for draw_id in range(BOOTSTRAP_DRAWS):
        draw = rng.choice(len(ids), size=len(ids), replace=True)
        idx = np.concatenate([positions[ids[i]] for i in draw])
        boot_s[draw_id] = float(contrast[idx].mean())
        if female[idx].any() and (~female[idx]).any():
            boot_g.append(gap(scenario[idx], female[idx]) - gap(base[idx], female[idx]))
    return boot_s, np.asarray(boot_g)


def attach_s_star(frame: pd.DataFrame) -> pd.DataFrame:
    hit = frame.loc[frame["recency"] >= 1, KEYS + ["week"]]
    s_star = hit.groupby(KEYS, as_index=False)["week"].min().rename(columns={"week": "s_star"})
    return frame.merge(s_star, on=KEYS, how="left")


def action_state(frame: pd.DataFrame) -> pd.DataFrame:
    state = frame[KEYS + ["week", "total_clicks", "recency", "streak", "submitted_this_week"]].copy()
    state["week"] = state["week"] + 1
    return state.rename(columns={"total_clicks": "clicks_action", "recency": "recency_action", "streak": "streak_action", "submitted_this_week": "submitted_action"})


def response_plan(frame: pd.DataFrame) -> pd.DataFrame:
    plan = frame[KEYS + ["week", "s_star"]].merge(action_state(frame), on=KEYS + ["week"], how="left", validate="1:1")
    s_star = plan["s_star"].to_numpy(dtype=float)
    week = plan["week"].to_numpy(dtype=float)
    plan["first_response"] = np.isfinite(s_star) & (week == s_star + 2) & plan["clicks_action"].notna().to_numpy()
    plan["second_response"] = np.isfinite(s_star) & (week == s_star + 3) & plan["clicks_action"].notna().to_numpy()
    return plan


def rewritten_features(frame: pd.DataFrame, plan: pd.DataFrame, alpha_first: float, alpha_second: float, enabled: bool) -> pd.DataFrame:
    features = frame[FEATURES].copy()
    if not enabled:
        return features
    response = plan["first_response"].to_numpy() | plan["second_response"].to_numpy()
    alpha = np.zeros(len(plan), dtype=float)
    alpha[plan["first_response"].to_numpy()] = alpha_first
    alpha[plan["second_response"].to_numpy()] = alpha_second
    clicks = plan["clicks_action"].to_numpy(dtype=float)
    features.loc[response, "total_clicks_lag"] = clicks[response] * (1.0 + alpha[response])
    features.loc[response, "recency_lag"] = 0.0
    features.loc[response, "streak_lag"] = np.maximum(plan.loc[response, "streak_action"].to_numpy(dtype=float), 1.0)
    features.loc[response, "submitted_lag"] = 1.0
    return features


def toy_response_window() -> None:
    rows = []
    for student, event_week in ((1, -1), (2, 1)):
        for week in range(4):
            rows.append({"id_student": student, "code_module": "AAA", "code_presentation": "2013J", "week": week, "recency": 1 if week == 0 else 0, "event": int(week == event_week)})
    toy = attach_s_star(pd.DataFrame(rows))
    week = toy["week"].to_numpy()
    s_star = toy["s_star"].to_numpy(dtype=float)
    response = np.isfinite(s_star) & ((week == s_star + 2) | (week == s_star + 3))
    if not np.array_equal(response[:4], response[4:]):
        raise RuntimeError("event label changed the response weeks")
    if not np.array_equal(response[:4], np.array([False, False, True, True])):
        raise RuntimeError("response window is not {s*+2, s*+3}")


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(brier_score_loss(y, p))
