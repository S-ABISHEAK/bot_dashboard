"""Named custom-layout library (the "Saved Layouts" panel).

Grid-cell validity (bounds, reachability, etc.) is `engine/layout.py`'s job
and is always run by the caller *before* a layout reaches this module —
`LayoutStore` only owns naming: uniqueness, length, and how many can be
saved. Backed by a single JSON file so saved layouts survive a server
restart; writes are atomic (write to a temp file, then os.replace) so a
crash mid-write never corrupts the store.
"""
import json
import os
import time
import uuid
from pathlib import Path

STORE_PATH = Path(__file__).parent.parent / "data" / "custom_layouts.json"
MAX_LAYOUTS = 50
MAX_NAME_LEN = 60


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LayoutStore:
    def __init__(self, path=STORE_PATH):
        self.path = Path(path)
        self._records = self._read()

    # ------------------------------------------------------------------
    def _read(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {}

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self._records, f, indent=2)
        os.replace(tmp, self.path)

    def _find_by_name(self, name, exclude_id=None):
        needle = name.strip().lower()
        for rid, rec in self._records.items():
            if rid != exclude_id and rec["name"].strip().lower() == needle:
                return rec
        return None

    # ------------------------------------------------------------------
    def list(self):
        return sorted(
            [{"id": r["id"], "name": r["name"], "created_at": r["created_at"],
              "updated_at": r["updated_at"]} for r in self._records.values()],
            key=lambda r: r["updated_at"], reverse=True,
        )

    def get(self, layout_id):
        return self._records.get(layout_id)

    def save_new(self, layout, base_name="Custom Layout", prefer_exact_name=False):
        """Save `layout` under a fresh, unique name - used when a
        newly-painted layout is applied without the operator having picked a
        name themselves, so nothing is ever lost for lack of a Save As
        click. With `prefer_exact_name` (imports), `base_name` is used as-is
        when it isn't already taken, instead of always stamping a
        timestamp onto it."""
        if prefer_exact_name and base_name and not self._find_by_name(base_name):
            return self.save_as(base_name, layout)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        name = f"{base_name} {stamp}"
        suffix = 2
        while self._find_by_name(name):
            name = f"{base_name} {stamp} ({suffix})"
            suffix += 1
        return self.save_as(name, layout)

    def update_layout(self, layout_id, layout):
        """Overwrite the cell data of an existing record in place (name and
        id unchanged) - used when re-applying edits to a layout that's
        already linked to a library entry."""
        rec = self._records.get(layout_id)
        if rec is None:
            return None
        rec["layout"] = layout
        rec["updated_at"] = _now()
        self._write()
        return rec

    def save_as(self, name, layout):
        name = (name or "").strip()
        if not name:
            return ["a name is required"]
        if len(name) > MAX_NAME_LEN:
            return [f"name is too long (max {MAX_NAME_LEN} characters)"]
        if self._find_by_name(name):
            return [f"a layout named '{name}' already exists"]
        if len(self._records) >= MAX_LAYOUTS:
            return [f"layout library is full ({MAX_LAYOUTS} saved) — delete one first"]
        rid = uuid.uuid4().hex[:8]
        now = _now()
        record = {"id": rid, "name": name, "layout": layout,
                  "created_at": now, "updated_at": now}
        self._records[rid] = record
        self._write()
        return record

    def rename(self, layout_id, new_name):
        rec = self._records.get(layout_id)
        if rec is None:
            return ["layout not found"]
        new_name = (new_name or "").strip()
        if not new_name:
            return ["a name is required"]
        if len(new_name) > MAX_NAME_LEN:
            return [f"name is too long (max {MAX_NAME_LEN} characters)"]
        if self._find_by_name(new_name, exclude_id=layout_id):
            return [f"a layout named '{new_name}' already exists"]
        rec["name"] = new_name
        rec["updated_at"] = _now()
        self._write()
        return rec

    def delete(self, layout_id):
        if layout_id not in self._records:
            return False
        del self._records[layout_id]
        self._write()
        return True
