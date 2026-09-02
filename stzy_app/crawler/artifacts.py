from __future__ import annotations

import os
import shutil
from pathlib import Path

from stzy_app.utils import ensure_directory


class ResourceArtifacts:
    """Owns the on-disk artifact layout for one downloaded resource."""

    def __init__(self, resource_dir: Path) -> None:
        self.resource_dir = resource_dir

    @property
    def original_dir(self) -> Path:
        return self.resource_dir / "original"

    @property
    def temp_pdf(self) -> Path:
        return self.resource_dir / "原文.pdf"

    @property
    def final_pdf(self) -> Path:
        return self.resource_dir.parent / f"{self.resource_dir.name}.pdf"

    def page_png(self, index: int) -> Path:
        return self.resource_dir / f"练习{index}.png"

    def prepare_resource_dir(self) -> None:
        ensure_directory(self.resource_dir)

    def prepare_original_dir(self) -> None:
        ensure_directory(self.original_dir)

    def publish_pdf(self, source_pdf: Path) -> Path:
        ensure_directory(self.final_pdf.parent)
        if source_pdf == self.final_pdf:
            return self.final_pdf
        os.replace(source_pdf, self.final_pdf)
        return self.final_pdf

    def cleanup_transient_artifacts(self) -> None:
        if self.original_dir.exists():
            shutil.rmtree(self.original_dir)
        if self.temp_pdf.exists():
            self.temp_pdf.unlink()
