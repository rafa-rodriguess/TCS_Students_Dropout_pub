from __future__ import annotations

import zipfile
from pathlib import Path
from urllib.request import urlopen

from .protocol import load_protocol

CSV_NAMES = (
    "studentInfo.csv",
    "studentRegistration.csv",
    "studentVle.csv",
    "studentAssessment.csv",
    "assessments.csv",
    "courses.csv",
    "vle.csv",
)


def safe_extract(zip_path: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            parts = Path(info.filename).parts
            if not parts or ".." in parts or parts[0] == "/":
                raise RuntimeError(f"caminho inseguro no zip: {info.filename}")
            name = parts[-1]
            if name not in CSV_NAMES:
                continue
            if name in written:
                raise RuntimeError(f"csv duplicado no zip: {name}")
            target = dest / name
            with archive.open(info) as source, target.open("wb") as handle:
                handle.write(source.read())
            written.append(name)
    missing = [name for name in CSV_NAMES if name not in written]
    if missing:
        raise RuntimeError(f"zip sem {missing}")
    return written


def run(ctx) -> dict:
    protocol = load_protocol()
    url = protocol.get("oulad_url")
    if not url:
        return {"status": "FAIL", "message": "URL ausente"}
    if not ctx.allow_download:
        return {"status": "DOWNLOAD_NOT_AUTHORIZED", "message": "download implementado e não autorizado nesta invocação"}
    ctx.raw.mkdir(parents=True, exist_ok=True)
    zip_path = ctx.raw / "oulad.zip"
    with urlopen(url, timeout=120) as response, zip_path.open("wb") as handle:
        handle.write(response.read())
    names = safe_extract(zip_path, ctx.raw)
    return {"status": "PASS", "message": f"extraídos {names}", "zip": str(zip_path)}
