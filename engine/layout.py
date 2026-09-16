"""Validation for a user-painted custom warehouse layout (the Layout Editor).

A custom layout is a plain dict:

    {
        "schema": "fleetnet.custom_layout.v1",
        "blocked":  [[x, y], ...],   # racks / interior walls
        "pickups":  [[x, y], ...],
        "dropoffs": [[x, y], ...],
        "chargers": [[x, y], ...],
        "depot":    [[x, y], ...],   # standby bays, order = bay number
    }

``validate()`` never raises on malformed input — every failure becomes a
human-readable string in the returned list, so a single Validate click in
the browser can surface every problem at once instead of stopping at the
first one.
"""
from . import config as C
from .world import World
from .planner import distance_field

ROLE_FIELDS = ("blocked", "pickups", "dropoffs", "chargers", "depot")
REQUIRED_MIN_COUNT = {"pickups": 1, "dropoffs": 1, "chargers": 1, "depot": 1}


def _in_bounds(x, y):
    return 0 <= x < C.GRID_W and 0 <= y < C.GRID_H


def _on_border(x, y):
    return x in (0, C.GRID_W - 1) or y in (0, C.GRID_H - 1)


def _coerce_cells(data, field, errors):
    """Return a list of (x, y) int tuples for `field`, logging any bad entry."""
    raw = data.get(field, [])
    if not isinstance(raw, list):
        errors.append(f"'{field}' must be a list of [x, y] pairs")
        return []
    cells = []
    for entry in raw:
        try:
            x, y = int(entry[0]), int(entry[1])
        except (TypeError, ValueError, IndexError, KeyError):
            errors.append(f"'{field}' has a malformed cell: {entry!r}")
            continue
        if not _in_bounds(x, y):
            errors.append(f"'{field}' cell ({x},{y}) is out of bounds "
                          f"(grid is {C.GRID_W}x{C.GRID_H})")
            continue
        if _on_border(x, y):
            errors.append(f"'{field}' cell ({x},{y}) is on the border wall "
                          f"— border cells are always walls and can't be used")
            continue
        cells.append((x, y))
    return cells


def validate(data):
    """Validate a custom layout dict. Returns a list of error strings
    (empty list = valid)."""
    errors = []
    if not isinstance(data, dict):
        return ["layout payload must be a JSON object"]

    by_field = {f: _coerce_cells(data, f, errors) for f in ROLE_FIELDS}

    # overlap: no cell may hold more than one role
    owner = {}
    for field, cells in by_field.items():
        for cell in cells:
            if cell in owner and owner[cell] != field:
                errors.append(f"cell {cell} is used as both "
                              f"'{owner[cell]}' and '{field}'")
            else:
                owner[cell] = field

    for field, minimum in REQUIRED_MIN_COUNT.items():
        if len(by_field[field]) < minimum:
            errors.append(f"need at least {minimum} '{field}' cell(s), "
                          f"found {len(by_field[field])}")

    if errors:
        return errors

    cleaned = {f: [list(c) for c in cells] for f, cells in by_field.items()}
    try:
        world = World(custom_layout=cleaned)
    except Exception as e:  # noqa: BLE001
        return [f"layout failed to build: {e}"]

    df = distance_field(world, world.depot[0])
    INF = 10 ** 6
    unreachable = []
    for field in ("pickups", "dropoffs", "chargers", "depot"):
        for (x, y) in getattr(world, field):
            if df[y, x] >= INF:
                unreachable.append(f"{field[:-1]} ({x},{y})")
    if unreachable:
        errors.append("unreachable from the depot: " + ", ".join(unreachable))

    return errors
