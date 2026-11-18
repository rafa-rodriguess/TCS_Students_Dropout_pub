from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Context:
    output_dir: Path
    allow_download: bool = False
    compare_baseline: bool = False
    compare_only: bool = False

    @property
    def raw(self) -> Path:
        return self.output_dir / "data" / "raw"

    @property
    def processed(self) -> Path:
        return self.output_dir / "data" / "processed"

    @property
    def models(self) -> Path:
        return self.output_dir / "models"

    @property
    def results(self) -> Path:
        return self.output_dir / "results"

    @property
    def curves(self) -> Path:
        return self.results / "curves"

    @property
    def figures(self) -> Path:
        return self.output_dir / "figures"

    @property
    def logs(self) -> Path:
        return self.output_dir / "logs"

    @property
    def checkpoints(self) -> Path:
        return self.output_dir / "checkpoints"

    def ensure_dirs(self) -> None:
        for path in (self.raw, self.processed, self.models, self.results, self.curves, self.figures, self.logs, self.checkpoints):
            path.mkdir(parents=True, exist_ok=True)
