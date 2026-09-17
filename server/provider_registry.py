# -*- coding: utf-8 -*-
"""Manifest-backed provider catalogue for the seven fixed slots."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_manifest(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location(f"manifest_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "MANIFEST", {}) or {})


class ProviderRegistry:
    def __init__(self, modules_root: Path):
        self.modules_root = Path(modules_root)

    def modules(self) -> list[dict]:
        rows = []
        for path in sorted(self.modules_root.glob("*/manifest.py")):
            manifest = _load_manifest(path)
            if manifest:
                rows.append(manifest)
        return rows

    def providers(self, slot_id: str | None = None) -> list[dict]:
        rows = []
        for module in self.modules():
            if slot_id and module.get("id") != slot_id:
                continue
            for provider in module.get("providers", []):
                rows.append({"slot_id": module.get("id"), "slot_name": module.get("name"), **provider})
        return rows

    def slot(self, slot_id: str) -> dict | None:
        return next((item for item in self.modules() if item.get("id") == slot_id), None)
