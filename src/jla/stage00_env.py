from __future__ import annotations

import sys

import joblib
import numpy
import pandas
import sklearn

from .paths import PACKAGE_ROOT
from .protocol import load_protocol


PINS = {
    "numpy": numpy.__version__,
    "pandas": pandas.__version__,
    "scikit-learn": sklearn.__version__,
    "joblib": joblib.__version__,
}


def locked_versions() -> dict[str, str]:
    found = {}
    for raw in (PACKAGE_ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        found[name.strip()] = version.strip()
    return found


def run(ctx) -> dict:
    del ctx
    protocol = load_protocol()
    if not protocol.get("oulad_url"):
        return {"status": "FAIL", "message": "protocolo sem URL do OULAD"}
    if "Path.home" in (PACKAGE_ROOT / "src" / "jla" / "science.py").read_text(encoding="utf-8"):
        return {"status": "FAIL", "message": "science.py ainda aponta para o diretório pessoal"}
    lock = locked_versions()
    missing = [name for name in PINS if name not in lock]
    if missing:
        return {"status": "FAIL", "message": f"lock sem {missing}"}
    mismatch = {name: (PINS[name], lock[name]) for name in PINS if PINS[name] != lock[name]}
    if mismatch:
        return {"status": "FAIL", "message": f"versão instalada diferente do lock: {mismatch}"}
    if sys.version_info < (3, 11):
        return {"status": "FAIL", "message": "Python anterior a 3.11"}
    return {"status": "PASS", "message": f"python {sys.version.split()[0]}; pins conferem com o host", "pins": PINS}
