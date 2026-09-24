"""Persists whichever custom layout is currently applied to the live map.

`engine/layout_store.py` holds the *named* Saved Layouts library. This
module holds just one extra thing: which layout (if any) is live on the
dashboard right now, so a server restart resumes the same map instead of
reverting to the built-in default. Same atomic-write pattern as
`layout_store.py` (write to a temp file, then os.replace).
"""
import json
import os
from pathlib import Path

STORE_PATH = Path(__file__).parent.parent / "data" / "active_layout.json"


def load_active_layout(path=STORE_PATH):
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("layout")
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        return None


def save_active_layout(layout, path=STORE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump({"layout": layout}, f, indent=2)
    os.replace(tmp, path)
