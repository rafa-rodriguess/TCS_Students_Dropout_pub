from __future__ import annotations

from pathlib import Path

from .paths import PACKAGE_ROOT


def _coerce(value: str):
    if value in {"null", "~", ""}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    try:
        if "." in value or "e" in value or "E" in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_protocol(path: Path | None = None) -> dict:
    path = path or (PACKAGE_ROOT / "config" / "protocol.yaml")
    data: dict = {}
    hashes: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("  ") and hashes is not None:
            key, value = line.strip().split(":", 1)
            hashes[key.strip()] = _coerce(value.strip())
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key == "hashes":
            hashes = {}
            data["hashes"] = hashes
        else:
            hashes = None
            data[key] = _coerce(value)
    return data
