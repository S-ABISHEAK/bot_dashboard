"""Persists whichever custom layout is currently applied to the live map.

`engine/layout_store.py` holds the *named* Saved Layouts library. This
module holds just one extra thing: which layout (if any) is live on the
dashboard right now, plus the id of the Saved Layouts record it's linked
to (if any), so a server restart resumes the same map *and* so re-applying
edits to it updates that same library entry instead of piling up
duplicates. Same atomic-write pattern as `layout_store.py` (write to a
temp file, then os.replace).
"""
import json
import os
from pathlib import Path

STORE_PATH = Path(__file__).parent.parent / "data" / "active_layout.json"


def load_active_layout(path=STORE_PATH):
    """Returns (layout, layout_id) - both None if nothing is active."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("layout"), data.get("layout_id")
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        return None, None


def save_active_layout(layout, layout_id=None, path=STORE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump({"layout": layout, "layout_id": layout_id if layout else None}, f, indent=2)
    os.replace(tmp, path)
