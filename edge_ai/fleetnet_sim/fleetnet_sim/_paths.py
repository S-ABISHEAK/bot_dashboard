"""Bootstraps ``Fleet_SIH/core`` onto ``sys.path``.

``Fleet_SIH`` is a plain repo (no packaging metadata) that we are
explicitly forbidden from modifying, so it can't be `pip install -e`'d.
This module makes its ``core`` package importable as ``core`` (matching
every internal import inside ``Fleet_SIH/core/*.py`` itself, e.g.
``from core.world import World``) by inserting the sibling repo root
onto ``sys.path`` once, at import time, before any ``fleetnet_sim``
module tries ``import core...``.

Layout assumed (Fleet_SIH a sibling directory, as the user's actual
environment has it -- warehouse_layout lives nested inside
fleetnet_sim/ instead and isn't relevant to this bootstrap):
    edge_ai/
      Fleet_SIH/          <- untouched, contains core/
      fleetnet_sim/       <- this package
        warehouse_layout/

If ``FLEET_SIH_ROOT`` is set in the environment, that path is used
instead (for a different checkout location).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_FLEET_SIH_ROOT = _THIS_DIR.parent.parent / "Fleet_SIH"

FLEET_SIH_ROOT = Path(os.environ.get("FLEET_SIH_ROOT", str(_DEFAULT_FLEET_SIH_ROOT))).resolve()

if not (FLEET_SIH_ROOT / "core").is_dir():
    raise ImportError(
        f"Fleet_SIH/core not found at {FLEET_SIH_ROOT} — set the FLEET_SIH_ROOT "
        "environment variable to the Fleet_SIH checkout root if it isn't a sibling "
        "of fleetnet_sim/."
    )

if str(FLEET_SIH_ROOT) not in sys.path:
    sys.path.insert(0, str(FLEET_SIH_ROOT))
