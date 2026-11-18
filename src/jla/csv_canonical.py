"""Gate SEMANTIC_CANONICAL_V1 para ausência codificada como '?'.

A troca de '?' por '' ocorre só na memória, só nas colunas autorizadas e só
para decidir equivalência. O CSV e o ZIP não são regravados. O processamento
científico continua lendo a fonte original. Hashes brutos do protocolo não
são substituídos pela medição nova.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

TARGETS = {
    "studentInfo.csv": ("imd_band",),
    "studentRegistration.csv": ("date_registration", "date_unregistration"),
    "studentAssessment.csv": ("score",),
    "assessments.csv": ("date",),
    "vle.csv": ("week_from", "week_to"),
    "courses.csv": (),
}
RAW_ONLY = "studentVle.csv"
CONTROL_PENDING = frozenset({"courses.csv", "vle.csv"})
CANDIDATE_MARKERS = ("", "?", "NA", "null", "NULL", "None")
REFERENCE_ORDERED_SHA256 = {
    "studentInfo.csv": "3a52cfe1731e5bd803cb2d4f32cbe33d802a88b33e159d4c78662f5404cc09c8",
    "studentRegistration.csv": "a41381b5de6a74deb309397af1a50e514bd3380d4a54947304a50fd41f32cbb4",
    "studentAssessment.csv": "c469563f624c2b8e64bd586795291f0e0fa83b5a67c7afa8c2de8664d2407830",
    "assessments.csv": "bc8524201dc26c5df1d30aba6a0527016dc11c0a874e64634b80f6aa6e5d9c19",
    "vle.csv": "38ddfd0e357271cfe8625eaa7023fb98a5dbf39819013dfd140d250ec4464119",
    "courses.csv": "cdfe42221a30146aa2936b78a448019ed0c790148bf8cc8aef4ea22f768221bd",
}
REFERENCE_MARKER_COUNTS = {
    "studentInfo.csv": {"imd_band": 1111},
    "studentRegistration.csv": {"date_registration": 45, "date_unregistration": 22521},
    "studentAssessment.csv": {"score": 173},
    "assessments.csv": {"date": 11},
    "vle.csv": {"week_from": 5243, "week_to": 5243},
    "courses.csv": {},
}


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def _sha_text_sequence(texts: list[str]) -> str:
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(bytes((10,)))
    return digest.hexdigest()


def measure(path: Path, targets: tuple[str, ...]) -> dict:
    """Mede o CSV com o algoritmo TCS_CSV_MISSING_CANONICAL_V1, sem gravar."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("csv vazio") from exc
        if len(set(header)) != len(header):
            raise ValueError("duplicate headers")
        if any(col not in header for col in targets):
            raise ValueError("missing target column")
        order = sorted(range(len(header)), key=lambda i: header[i])
        columns = [header[i] for i in order]
        marker_counts = {col: {marker: 0 for marker in CANDIDATE_MARKERS} for col in targets}
        question_outside = 0
        rows: list[str] = []
        for rownum, values in enumerate(reader, start=2):
            if len(values) != len(header):
                raise ValueError("arity mismatch record=" + str(rownum))
            vals = [values[i] for i in order]
            for col, val in zip(columns, vals):
                if val == "?" and col not in targets:
                    question_outside += 1
                if col in targets and val in CANDIDATE_MARKERS:
                    marker_counts[col][val] += 1
            normalized = ["" if col in targets and val == "?" else val for col, val in zip(columns, vals)]
            rows.append(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
    header_text = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
    return {
        "ordered_sha256": _sha_text_sequence([header_text] + rows),
        "marker_counts": marker_counts,
        "question_outside": question_outside,
        "data_rows": len(rows),
        "columns": columns,
    }


def _fail(name: str, reason: str, *, observed: str | None = None, expected: str | None = None) -> dict:
    payload = {
        "file": name,
        "status": "FAIL",
        "message": f"hash divergente em {name}; {reason}; esperado não foi alterado",
        "validation_mode": "FAIL",
    }
    if observed is not None:
        payload["observed"] = observed
    if expected is not None:
        payload["expected"] = expected
    return payload


def decide(
    path: Path,
    name: str,
    expected_raw: str | None,
    *,
    ordered_reference: str | None = None,
    marker_reference: dict[str, int] | None = None,
) -> dict:
    """Decide PASS_RAW, equivalência semântica ou FAIL. Não altera o arquivo."""
    observed = sha_file(path)
    if name == RAW_ONLY or (expected_raw and observed == expected_raw):
        if expected_raw and observed == expected_raw:
            return {
                "file": name,
                "status": "PASS",
                "validation_mode": "PASS_RAW",
                "observed": observed,
                "expected": expected_raw,
            }
        return _fail(name, "hash bruto obrigatório não confere", observed=observed, expected=expected_raw)
    if name not in TARGETS:
        return _fail(name, "arquivo não elegível para equivalência semântica", observed=observed, expected=expected_raw)
    try:
        measured = measure(path, TARGETS[name])
    except (ValueError, csv.Error) as exc:
        return _fail(name, "formato inválido: " + str(exc), observed=observed, expected=expected_raw)
    if measured["question_outside"]:
        return _fail(name, "marcador ? fora da coluna autorizada", observed=observed, expected=expected_raw)
    ref_ordered = REFERENCE_ORDERED_SHA256[name] if ordered_reference is None else ordered_reference
    ref_counts = REFERENCE_MARKER_COUNTS[name] if marker_reference is None else marker_reference
    for col, expected_n in ref_counts.items():
        got = measured["marker_counts"].get(col, {})
        if any(got.get(marker, 0) for marker in CANDIDATE_MARKERS if marker != "?"):
            return _fail(name, f"marcador diferente de ? em {col}", observed=observed, expected=expected_raw)
        if got.get("?", 0) != expected_n:
            return _fail(name, f"contagem de ? em {col} não confere", observed=observed, expected=expected_raw)
    if measured["ordered_sha256"] != ref_ordered:
        return _fail(name, "digest ordenado não confere", observed=observed, expected=expected_raw)
    payload = {
        "file": name,
        "validation_mode": "SEMANTIC_CANONICAL_V1",
        "observed": observed,
        "expected": expected_raw,
        "ordered_sha256": measured["ordered_sha256"],
        "question_mark_counts": {col: measured["marker_counts"][col]["?"] for col in measured["marker_counts"]},
    }
    if expected_raw in (None, "null"):
        payload["status"] = "PENDING"
        return payload
    payload["status"] = "PASS"
    return payload
