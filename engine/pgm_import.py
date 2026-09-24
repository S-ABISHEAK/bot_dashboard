"""Import a .pgm occupancy-grid image into the blocked-cell structure of a
custom layout (the Layout Editor). PGM ("Portable Gray Map") is the
standard grayscale format used for robotics/ROS floor-plan maps: white
pixels are free floor, black pixels are walls/obstacles.

Only the blocked/rack structure comes from the image — pickups, dropoffs,
chargers and depot bays are FleetNet-specific concepts a grayscale image
has no way to express, so the caller seeds an editor buffer with an empty
zone set and the operator places those by hand afterward.
"""
import re

import numpy as np

from . import config as C

MAX_DIM = 2000


class PgmError(ValueError):
    pass


def parse_pgm(raw: bytes) -> np.ndarray:
    """Parse a P2 (ASCII) or P5 (binary) PGM file into a (h, w) uint8 array."""
    if len(raw) < 2 or raw[:2] not in (b"P2", b"P5"):
        raise PgmError("not a PGM file (expected a P2 or P5 header)")
    magic = raw[:2].decode("ascii")

    # Walk the three whitespace-separated header tokens (width, height,
    # maxval) that follow the magic number, skipping '#' comment lines,
    # exactly as the PGM spec requires.
    pos = 2
    tokens = []
    while len(tokens) < 3:
        while pos < len(raw) and raw[pos:pos + 1].isspace():
            pos += 1
        if pos < len(raw) and raw[pos:pos + 1] == b"#":
            nl = raw.find(b"\n", pos)
            pos = len(raw) if nl == -1 else nl + 1
            continue
        start = pos
        while pos < len(raw) and not raw[pos:pos + 1].isspace():
            pos += 1
        if start == pos:
            raise PgmError("malformed PGM header")
        tokens.append(raw[start:pos])
    try:
        width, height, maxval = (int(t) for t in tokens)
    except ValueError:
        raise PgmError("malformed PGM header (width/height/maxval)")
    if width <= 0 or height <= 0:
        raise PgmError("PGM has invalid dimensions")
    if width > MAX_DIM or height > MAX_DIM:
        raise PgmError(f"PGM is too large (max {MAX_DIM}x{MAX_DIM} pixels)")
    if not (0 < maxval < 65536):
        raise PgmError("PGM has an invalid maxval")
    pos += 1  # single whitespace byte after maxval

    n = width * height
    if magic == "P5":
        sample_bytes = 1 if maxval < 256 else 2
        body = raw[pos:pos + n * sample_bytes]
        if len(body) < n * sample_bytes:
            raise PgmError("PGM pixel data is truncated")
        dtype = ">u2" if sample_bytes == 2 else "u1"
        pixels = np.frombuffer(body, dtype=dtype, count=n).astype(np.float64)
    else:
        text = raw[pos:].decode("ascii", errors="ignore")
        values = re.findall(r"\d+", text)
        if len(values) < n:
            raise PgmError("PGM pixel data is truncated")
        pixels = np.array(values[:n], dtype=np.float64)

    # normalise to 0..255 regardless of the file's own maxval
    gray = (pixels * (255.0 / maxval)).astype(np.uint8).reshape(height, width)
    return gray


def pgm_to_blocked_cells(raw: bytes):
    """Returns (blocked_cells, errors). blocked_cells is a list of [x, y]
    pairs sized to the sim's fixed GRID_W x GRID_H grid, with the border
    ring always excluded (it's already a wall)."""
    try:
        gray = parse_pgm(raw)
    except PgmError as e:
        return [], [str(e)]

    src_h, src_w = gray.shape
    # nearest-neighbor resample onto the fixed grid — keeps wall edges
    # crisp for what's typically a mostly-binary floor-plan image
    ys = (np.arange(C.GRID_H) * src_h // C.GRID_H).clip(0, src_h - 1)
    xs = (np.arange(C.GRID_W) * src_w // C.GRID_W).clip(0, src_w - 1)
    resized = gray[np.ix_(ys, xs)]

    blocked_mask = resized < 128
    blocked = []
    for y in range(C.GRID_H):
        if y in (0, C.GRID_H - 1):
            continue
        for x in range(C.GRID_W):
            if x in (0, C.GRID_W - 1):
                continue
            if blocked_mask[y, x]:
                blocked.append([x, y])
    return blocked, []
