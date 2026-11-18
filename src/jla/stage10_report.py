from __future__ import annotations

import json

from .audit import assemble_found, baseline_map, classify_hashes, compare_baseline, write_svg
from .checkpoint import fingerprint, input_token, load_state, output_token, reusable
from .paths import PACKAGE_ROOT
from .protocol import load_protocol
from .science import sha256_file

PRODUCTS = [
    {"id": "tab:cohort_split", "status": "GERAR", "source": "etapas 03 e 04"},
    {"id": "fig:calibration_main", "status": "GERAR", "source": "results/curves/calibration_bins.csv"},
    {"id": "fig:survival_baseline_rq1", "status": "LEGADO/DECISAO A7", "source": "media semanal observada nao e curva de coorte fixa"},
    {"id": "fig:censoring_survival_results", "status": "GERAR", "source": "results/curves/censoring_g.csv"},
    {"id": "tab:rq2_summary", "status": "GERAR", "source": "results/p3_metrics.json"},
    {"id": "tab:benchmark_horizon_results", "status": "NOT_SUPPORTED", "source": None},
    {"id": "tab:app_boot_tp", "status": "NOT_SUPPORTED", "source": None},
    {"id": "disability_gap", "status": "NOT_SUPPORTED", "source": None},
    {"id": "fig:framework_overview", "status": "DECISÃO EDITORIAL A7", "source": None},
]


REQUIRED = ("p1_metrics.json", "p2_metrics.json", "p3_metrics.json", "censoring.json", "operator_tests.json", "equity.json", "landmark.json")
SOURCES = {"p1": "p1_metrics.json", "p2": "p2_metrics.json", "p3": "p3_metrics.json", "a3": "censoring.json", "a4": "operator_tests.json", "a5": "equity.json", "landmark": "landmark.json"}


def _libraries() -> dict:
    import joblib
    import numpy
    import pandas
    import sklearn
    import sys

    return {"python": sys.version.split()[0], "numpy": numpy.__version__, "pandas": pandas.__version__, "sklearn": sklearn.__version__, "joblib": joblib.__version__}


def _digest(path) -> str | None:
    return sha256_file(path) if path.exists() else None


def _write_manifest(ctx, verification: str) -> None:
    inputs = {
        "protocol.yaml": _digest(PACKAGE_ROOT / "config" / "protocol.yaml"),
        "requirements.lock": _digest(PACKAGE_ROOT / "requirements.lock"),
    }
    inputs.update({name: _digest(ctx.results / name) for name in REQUIRED})
    outputs = {name: _digest(ctx.results / name) for name in ("product_matrix.json", "baseline_map.json", "baseline_compare.json")}
    payload = {
        "fingerprint": fingerprint(),
        "libraries": _libraries(),
        "inputs": inputs,
        "outputs": outputs,
        "verification_status": verification,
        "publication_status": "BLOCKED",
    }
    (ctx.results / "manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _scientific_checkpoint(ctx) -> tuple[str, str] | None:
    state = load_state(ctx)
    if not state.get("stages"):
        return ("FAIL", "checkpoint vazio")
    current = fingerprint()
    if state.get("fingerprint") != current:
        return ("FAIL", "checkpoint obsoleto")
    for name in [f"{index:02d}" for index in range(10)]:
        if not reusable(state, name, current, input_token(ctx, name), output_token(ctx, name)):
            return ("FAIL", f"checkpoint da etapa {name} invalido")
    if state["stages"]["08"].get("scope") != "REAL":
        return ("BLOCKED", "A4 nao e REAL")
    public = ctx.results / "public_examples.json"
    if public.exists():
        payload = json.loads(public.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("scope") in {"MOCK", "PASS_MOCK"}:
            return ("BLOCKED", "A4 PASS_MOCK nao autoriza reproducao")
    return None


def _verification(rows: list[dict], ctx) -> str:
    if any(row["status"] == "FAIL" for row in rows):
        return "FAIL"
    hashes = classify_hashes(ctx.raw, load_protocol().get("hashes", {}))
    pending = any(row["status"] in {"PENDING", "ABSENT", "FAIL"} for row in hashes)
    if pending or any(row["status"] == "BLOCKED" for row in rows):
        return "BLOCKED"
    if rows and all(row["status"] == "PASS" for row in rows):
        return "PASS"
    return "FAIL"


def run(ctx) -> dict:
    ctx.results.mkdir(parents=True, exist_ok=True)
    (ctx.results / "product_matrix.json").write_text(json.dumps(PRODUCTS, indent=2), encoding="utf-8")
    (ctx.results / "baseline_map.json").write_text(json.dumps(baseline_map(), indent=2), encoding="utf-8")
    for name in ("calibration_bins.csv", "censoring_g.csv"):
        path = ctx.curves / name
        if not path.exists():
            continue
        import pandas as pd

        series = pd.read_csv(path)
        value_column = "mean_p" if "mean_p" in series.columns else "mean_S_base" if "mean_S_base" in series.columns else "g"
        if value_column in series.columns:
            write_svg(ctx.figures / f"{path.stem}.svg", [float(v) for v in series[value_column].dropna()])
            (ctx.figures / "NAO_VALIDADO.txt").write_text("SVG de rascunho. Não é figura científica final.\n", encoding="utf-8")
    if not ctx.compare_baseline:
        if not (ctx.results / "p3_metrics.json").exists():
            _write_manifest(ctx, "BLOCKED")
            return {"status": "NOT_RUN_SCIENCE", "verification_status": "BLOCKED", "publication_status": "BLOCKED", "message": "sem métricas corrigidas; legado permanece NOT_SUPPORTED"}
        _write_manifest(ctx, "BLOCKED")
        return {"status": "PASS_EDITORIAL", "verification_status": "BLOCKED", "publication_status": "BLOCKED", "message": "producao editorial escrita; nao e reproducao cientifica"}
    missing = []
    if not (ctx.checkpoints / "state.json").exists():
        missing.append("checkpoint")
    missing.extend(name for name in REQUIRED if not (ctx.results / name).exists())
    if missing:
        _write_manifest(ctx, "FAIL")
        return {"status": "FAIL", "verification_status": "FAIL", "publication_status": "BLOCKED", "message": "checkpoint ou dado ausente: " + ", ".join(missing)}
    gate = _scientific_checkpoint(ctx)
    if gate is not None:
        status, message = gate
        verification = "BLOCKED" if status == "BLOCKED" else "FAIL"
        _write_manifest(ctx, verification)
        return {"status": status, "verification_status": verification, "publication_status": "BLOCKED", "message": message}
    parts = {key: json.loads((ctx.results / name).read_text(encoding="utf-8")) for key, name in SOURCES.items()}
    baseline = json.loads((PACKAGE_ROOT / "baselines" / "aggregates.json").read_text(encoding="utf-8"))
    rows = compare_baseline(assemble_found(parts), baseline)
    (ctx.results / "baseline_compare.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    verification = _verification(rows, ctx)
    _write_manifest(ctx, verification)
    if verification == "PASS":
        return {"status": "PASS_REPRODUCTION", "verification_status": "PASS", "publication_status": "BLOCKED", "message": "reproducao numerica confere; publicacao continua bloqueada"}
    if verification == "BLOCKED":
        return {"status": "BLOCKED", "verification_status": "BLOCKED", "publication_status": "BLOCKED", "message": "reproducao bloqueada por hash pendente ou float por confirmar"}
    return {"status": "FAIL", "verification_status": "FAIL", "publication_status": "BLOCKED", "message": "comparacao divergente"}
