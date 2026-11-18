import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import classify_hashes  # noqa: E402
from jla.csv_canonical import (  # noqa: E402
    REFERENCE_MARKER_COUNTS,
    REFERENCE_ORDERED_SHA256,
    decide,
    measure,
    sha_file,
)
from jla.protocol import load_protocol  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_reference_constants_match_the_audited_digests():
    assert REFERENCE_ORDERED_SHA256["studentInfo.csv"] == "3a52cfe1731e5bd803cb2d4f32cbe33d802a88b33e159d4c78662f5404cc09c8"
    assert REFERENCE_ORDERED_SHA256["studentRegistration.csv"] == "a41381b5de6a74deb309397af1a50e514bd3380d4a54947304a50fd41f32cbb4"
    assert REFERENCE_ORDERED_SHA256["studentAssessment.csv"] == "c469563f624c2b8e64bd586795291f0e0fa83b5a67c7afa8c2de8664d2407830"
    assert REFERENCE_ORDERED_SHA256["assessments.csv"] == "bc8524201dc26c5df1d30aba6a0527016dc11c0a874e64634b80f6aa6e5d9c19"
    assert REFERENCE_ORDERED_SHA256["vle.csv"] == "38ddfd0e357271cfe8625eaa7023fb98a5dbf39819013dfd140d250ec4464119"
    assert REFERENCE_ORDERED_SHA256["courses.csv"] == "cdfe42221a30146aa2936b78a448019ed0c790148bf8cc8aef4ea22f768221bd"
    assert REFERENCE_MARKER_COUNTS["studentInfo.csv"]["imd_band"] == 1111
    assert REFERENCE_MARKER_COUNTS["studentRegistration.csv"] == {"date_registration": 45, "date_unregistration": 22521}
    assert REFERENCE_MARKER_COUNTS["vle.csv"] == {"week_from": 5243, "week_to": 5243}


def test_raw_match_passes_without_rewriting(tmp_path):
    path = tmp_path / "studentVle.csv"
    _write(path, "id_student,code_module,code_presentation,date,sum_click\n1,A,B,0,3\n")
    before = path.read_bytes()
    decision = decide(path, "studentVle.csv", sha_file(path))
    assert decision["status"] == "PASS"
    assert decision["validation_mode"] == "PASS_RAW"
    assert path.read_bytes() == before


def test_question_mark_only_in_authorized_column_passes_and_source_stays(tmp_path):
    path = tmp_path / "assessments.csv"
    _write(path, "code_module,date,id_assessment\nAAA,10,1\nBBB,?,2\n")
    measured = measure(path, ("date",))
    before = path.read_bytes()
    decision = decide(
        path,
        "assessments.csv",
        "0" * 64,
        ordered_reference=measured["ordered_sha256"],
        marker_reference={"date": 1},
    )
    assert decision["status"] == "PASS"
    assert decision["validation_mode"] == "SEMANTIC_CANONICAL_V1"
    assert decision["observed"] == _sha(path)
    assert path.read_bytes() == before
    assert b"?" in before


def test_question_mark_outside_target_fails(tmp_path):
    path = tmp_path / "assessments.csv"
    _write(path, "code_module,date,id_assessment\n?,10,1\n")
    measured = measure(path, ("date",))
    decision = decide(path, "assessments.csv", "0" * 64, ordered_reference=measured["ordered_sha256"], marker_reference={"date": 0})
    assert decision["status"] == "FAIL"
    assert "fora da coluna autorizada" in decision["message"]


def test_reordered_rows_fail_ordered_digest(tmp_path):
    original = tmp_path / "assessments.csv"
    _write(original, "code_module,date,id_assessment\nAAA,?,1\nBBB,10,2\n")
    measured = measure(original, ("date",))
    swapped = tmp_path / "swapped.csv"
    _write(swapped, "code_module,date,id_assessment\nBBB,10,2\nAAA,?,1\n")
    decision = decide(
        swapped,
        "assessments.csv",
        "0" * 64,
        ordered_reference=measured["ordered_sha256"],
        marker_reference={"date": 1},
    )
    assert decision["status"] == "FAIL"
    assert "digest ordenado" in decision["message"]


def test_changed_value_added_row_other_marker_and_count_fail(tmp_path):
    base = tmp_path / "assessments.csv"
    _write(base, "code_module,date,id_assessment\nAAA,?,1\n")
    measured = measure(base, ("date",))
    changed = tmp_path / "changed.csv"
    _write(changed, "code_module,date,id_assessment\nAAA,?,9\n")
    added = tmp_path / "added.csv"
    _write(added, "code_module,date,id_assessment\nAAA,?,1\nBBB,3,2\n")
    other = tmp_path / "other.csv"
    _write(other, "code_module,date,id_assessment\nAAA,NA,1\n")
    counted = tmp_path / "counted.csv"
    _write(counted, "code_module,date,id_assessment\nAAA,?,1\nBBB,?,2\n")
    kwargs = {"ordered_reference": measured["ordered_sha256"], "marker_reference": {"date": 1}}
    assert decide(changed, "assessments.csv", "0" * 64, **kwargs)["status"] == "FAIL"
    assert decide(added, "assessments.csv", "0" * 64, **kwargs)["status"] == "FAIL"
    assert "marcador diferente" in decide(other, "assessments.csv", "0" * 64, **kwargs)["message"]
    assert "contagem" in decide(counted, "assessments.csv", "0" * 64, marker_reference={"date": 1}, ordered_reference=measure(counted, ("date",))["ordered_sha256"])["message"]


def test_invalid_arity_fails(tmp_path):
    path = tmp_path / "assessments.csv"
    _write(path, "code_module,date,id_assessment\nonly\n")
    decision = decide(path, "assessments.csv", "0" * 64)
    assert decision["status"] == "FAIL"
    assert "formato inválido" in decision["message"]


def test_student_vle_rejects_semantic_fallback(tmp_path):
    path = tmp_path / "studentVle.csv"
    _write(path, "id_student,code_module,code_presentation,date,sum_click\n1,A,B,?,3\n")
    decision = decide(path, "studentVle.csv", "f" * 64)
    assert decision["status"] == "FAIL"
    assert decision["validation_mode"] == "FAIL"


def test_pending_control_keeps_protocol_shape_and_mismatch_fails(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "courses.csv").write_text("code_module\nZZZ\n", encoding="utf-8")
    protocol = load_protocol()
    before = dict(protocol["hashes"])
    rows = classify_hashes(raw, protocol["hashes"])
    assert protocol["hashes"] == before
    pending = [row for row in rows if row["status"] == "PENDING"]
    assert pending
    assert all(row["expected"] is None and "observed" not in row for row in pending)
    courses = next(row for row in rows if row["file"] == "courses.csv")
    assert courses["status"] == "FAIL"
    assert courses["observed"] != REFERENCE_ORDERED_SHA256["courses.csv"]
