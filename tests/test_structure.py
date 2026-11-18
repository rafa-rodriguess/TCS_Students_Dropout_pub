import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.paths import Context  # noqa: E402
from jla.science import clock_toy, toy_active_ignores_event, toy_response_window  # noqa: E402
from jla.stage01_download import safe_extract  # noqa: E402
from jla.stage02_validate import run as validate  # noqa: E402


def test_help_and_plan():
    help_run = subprocess.run([sys.executable, str(ROOT / "orquestrator.py"), "--help"], check=False, capture_output=True, text=True)
    assert help_run.returncode == 0
    assert "--resume" in help_run.stdout
    plan = subprocess.run([sys.executable, str(ROOT / "orquestrator.py"), "--plan"], check=False, capture_output=True, text=True)
    assert plan.returncode == 0
    for name in [f"{i:02d}" for i in range(11)]:
        assert f"ETAPA {name}" in plan.stdout


def test_all_stops_before_download(tmp_path):
    run = subprocess.run(
        [sys.executable, str(ROOT / "orquestrator.py"), "--all", "--output-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2
    assert "DOWNLOAD_NOT_AUTHORIZED" in run.stdout
    assert "NOT_RUN_SCIENCE" not in run.stdout
    assert not (tmp_path / "data" / "raw" / "oulad.zip").exists()


def test_missing_csv_fails_closed(tmp_path):
    result = validate(Context(output_dir=tmp_path))
    assert result["status"] == "FAIL"
    assert "ausente" in result["message"]


def test_hash_mismatch_does_not_rewrite_protocol(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    header = {
        "studentInfo.csv": "id_student,code_module,code_presentation,final_result,gender\n",
        "studentRegistration.csv": "id_student,code_module,code_presentation,date_unregistration\n",
        "studentVle.csv": "id_student,code_module,code_presentation,date,sum_click\n",
        "studentAssessment.csv": "id_assessment\n",
        "assessments.csv": "id_assessment\n",
        "courses.csv": "code_module\n",
        "vle.csv": "id_site\n",
    }
    for name, text in header.items():
        (raw / name).write_text(text + "x\n", encoding="utf-8")
    before = (ROOT / "config" / "protocol.yaml").read_text(encoding="utf-8")
    result = validate(Context(output_dir=tmp_path))
    assert result["status"] == "FAIL"
    assert "divergente" in result["message"]
    assert (ROOT / "config" / "protocol.yaml").read_text(encoding="utf-8") == before


def test_zip_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../studentInfo.csv", "id\n")
    try:
        safe_extract(archive, tmp_path / "out")
    except RuntimeError as exc:
        assert "inseguro" in str(exc)
    else:
        raise AssertionError("zip com caminho relativo foi aceito")


def test_toys_do_not_fit():
    toy_active_ignores_event()
    toy_response_window()
    clock = clock_toy()
    assert clock["G18"] == 1.0


def test_gitignore_covers_private_outputs():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for piece in ("data/", "results/", "figures/", "*.joblib", ".env"):
        assert piece in text


def test_resume_reuses_stage00(tmp_path):
    cmd = [sys.executable, str(ROOT / "orquestrator.py"), "--stage", "00", "--output-dir", str(tmp_path)]
    first = subprocess.run(cmd, check=False, capture_output=True, text=True)
    second = subprocess.run(cmd + ["--resume"], check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "retomada" in second.stdout
