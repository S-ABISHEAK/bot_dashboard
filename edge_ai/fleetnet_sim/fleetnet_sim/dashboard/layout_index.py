"""Scans directories of warehouse_layout-generated JSON files and builds
a lightweight index (layout_id -> path + summary metadata) for the
dashboard's layout browser. There is no existing "list layouts" helper
anywhere in this project (only `fleetnet_sim/cli/main.py`'s
`_resolve_layouts`, a bare directory glob for the CLI's `batch`
command) — this is new.

The scan result is cached in memory keyed by a cheap signature (file
count + max mtime) per directory tuple, so repeated `GET /api/layouts`
calls don't re-parse every JSON file on every request; the cache is
invalidated automatically the moment a file is added/removed/modified.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_LAYOUT_DIRS = [
    "warehouse_layout/outputs/layouts",
    "warehouse_layout/outputs/layouts_batch",
]


def _dir_signature(d: Path) -> tuple[int, float]:
    files = list(d.glob("*.json")) if d.is_dir() else []
    return (len(files), max((f.stat().st_mtime for f in files), default=0.0))


class LayoutIndex:
    def __init__(self, dirs: list[str]):
        self.dirs = [Path(d) for d in dirs]
        self._cache_sig: tuple | None = None
        self._by_id: dict[str, dict] = {}

    def _rebuild_if_stale(self) -> None:
        sig = tuple(_dir_signature(d) for d in self.dirs)
        if sig == self._cache_sig:
            return
        by_id: dict[str, dict] = {}
        for d in self.dirs:
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.json")):
                try:
                    with open(path) as f:
                        data = json.load(f)
                    layout_id = data.get("layout_id", path.stem)
                    warehouse = data.get("warehouse", {})
                    by_id[layout_id] = {
                        "layout_id": layout_id,
                        "path": str(path),
                        "archetype": warehouse.get("archetype"),
                        "scale_class": warehouse.get("scale_class"),
                        "industry_type": warehouse.get("industry_type"),
                        "area_m2": warehouse.get("area_m2"),
                        "aspect_ratio": warehouse.get("aspect_ratio"),
                        "valid": data.get("validation", {}).get("valid", False),
                        "file_size_kb": round(path.stat().st_size / 1024, 1),
                    }
                except (json.JSONDecodeError, OSError) as exc:
                    # A malformed/half-written file shouldn't take down
                    # the whole browser — skip it, keep scanning.
                    by_id[f"__error__{path.name}"] = {"layout_id": path.stem, "path": str(path), "error": str(exc)}
        self._by_id = by_id
        self._cache_sig = sig

    def list_summaries(self) -> list[dict]:
        self._rebuild_if_stale()
        return list(self._by_id.values())

    def find_path(self, layout_id: str) -> Path | None:
        self._rebuild_if_stale()
        entry = self._by_id.get(layout_id)
        return Path(entry["path"]) if entry else None
