"""
heatmap.py - Turns WiFi survey samples into a heat map.

Steps:
  1. signal_at()       pick ONE dBm value from each Sample (connected AP, an SSID, or a BSSID)
  2. idw_grid()        estimate the signal everywhere between samples with IDW
  3. coverage_summary() % of the area that is good / weak / dead
  4. make_overlay()    color the grid red-yellow-green as a see-through image
"""

from __future__ import annotations

import numpy as np
from matplotlib import colormaps
from PIL import Image

from wifi_scanner import NOISE_FLOOR_DBM, Sample


# ---------------------------------------------------------------------------
# Signal quality thresholds (common WiFi rules of thumb)
# ---------------------------------------------------------------------------

GOOD_DBM = -67.0   # at or above: good enough for video calls / streaming
WEAK_DBM = -80.0   # at or above: usable but slow; below this = dead zone

# Color scale range: -90 dBm (or worse) = full red, -50 dBm (or better) = full green
COLOR_MIN_DBM = -90.0
COLOR_MAX_DBM = -50.0


# ---------------------------------------------------------------------------
# 1. Pick the signal we care about from each sample
# ---------------------------------------------------------------------------

def signal_at(sample: Sample, mode: str = "connected", target: str = "") -> float:
    """
    Return the dBm value to map for one Sample.

    mode:
      "connected" - the AP we're connected to
      "ssid"      - strongest AP whose network name equals `target`
      "bssid"     - the one AP radio whose MAC address equals `target`
      "strongest" - strongest AP of any network

    If nothing matches (the network wasn't heard here), return the noise floor,
    so the spot shows up as a dead zone - that's real information.
    """
    if mode == "connected":
        matches = [r for r in sample.readings if r.connected]
    elif mode == "ssid":
        matches = [r for r in sample.readings if r.ssid == target]
    elif mode == "bssid":
        matches = [r for r in sample.readings if r.bssid == target.lower()]
    elif mode == "strongest":
        matches = sample.readings
    else:
        raise ValueError(f"Unknown mode: {mode!r}")

    if not matches:
        return NOISE_FLOOR_DBM
    return max(r.dbm for r in matches)


# ---------------------------------------------------------------------------
# 2. IDW (Inverse Distance Weighting) interpolation
# ---------------------------------------------------------------------------

def idw_grid(points: list[tuple[float, float, float]], width: int, height: int,
             power: float = 2.0, step: int = 4) -> np.ndarray:
    """
    Estimate the signal at every cell of a grid covering a width x height image.

    points: list of (x, y, dbm) survey measurements, in image pixels.
    step:   grid cell size in pixels (4 = one estimate per 4x4 block, for speed).

    IDW formula for each cell:
        weight_i = 1 / distance_i ** power
        value    = sum(weight_i * dbm_i) / sum(weight_i)
    Nearby points count much more than far ones. power=2 is the usual choice.

    Returns a 2-D array of dBm values, shape (rows, cols).
    """
    if not points:
        raise ValueError("Need at least one survey point to build a heat map.")

    # Centers of each grid cell, in pixels.
    cols = int(np.ceil(width / step))
    rows = int(np.ceil(height / step))
    cell_x = (np.arange(cols) + 0.5) * step
    cell_y = (np.arange(rows) + 0.5) * step
    grid_x, grid_y = np.meshgrid(cell_x, cell_y)          # each shape (rows, cols)

    px = np.array([p[0] for p in points])
    py = np.array([p[1] for p in points])
    pv = np.array([p[2] for p in points])

    # Distance from every cell to every point: shape (rows, cols, n_points).
    dist = np.sqrt((grid_x[..., None] - px) ** 2 + (grid_y[..., None] - py) ** 2)

    # A tiny minimum distance avoids dividing by zero when a cell sits exactly
    # on a point; that point's huge weight then makes the cell equal its value.
    weights = 1.0 / np.maximum(dist, 1e-6) ** power
    return (weights * pv).sum(axis=2) / weights.sum(axis=2)


# ---------------------------------------------------------------------------
# 3. Coverage summary
# ---------------------------------------------------------------------------

def classify(dbm: float) -> str:
    """Label one dBm value as 'good', 'weak' or 'dead'."""
    if dbm >= GOOD_DBM:
        return "good"
    if dbm >= WEAK_DBM:
        return "weak"
    return "dead"


def coverage_summary(grid: np.ndarray) -> dict[str, float]:
    """Percent of grid cells that are good / weak / dead (adds up to 100)."""
    total = grid.size
    good = np.count_nonzero(grid >= GOOD_DBM)
    weak = np.count_nonzero((grid >= WEAK_DBM) & (grid < GOOD_DBM))
    dead = total - good - weak
    return {
        "good": 100.0 * good / total,
        "weak": 100.0 * weak / total,
        "dead": 100.0 * dead / total,
    }


# ---------------------------------------------------------------------------
# 4. Colored overlay image
# ---------------------------------------------------------------------------

def make_overlay(grid: np.ndarray, width: int, height: int, alpha: int = 120) -> Image.Image:
    """
    Color the dBm grid red -> yellow -> green and return a see-through RGBA image
    the same size as the floor plan, ready to paste on top of it.

    alpha: 0 = invisible, 255 = solid (120 lets the floor plan show through).
    """
    # Scale dBm to 0..1 for the colormap (0 = red/weak, 1 = green/strong).
    scaled = (grid - COLOR_MIN_DBM) / (COLOR_MAX_DBM - COLOR_MIN_DBM)
    scaled = np.clip(scaled, 0.0, 1.0)

    rgba = colormaps["RdYlGn"](scaled)                    # floats 0..1, shape (rows, cols, 4)
    rgba = (rgba * 255).astype(np.uint8)
    rgba[..., 3] = alpha                                  # same transparency everywhere

    # A (rows, cols, 4) uint8 array is read as an RGBA image automatically.
    small = Image.fromarray(rgba)
    # Stretch the coarse grid up to full size; BILINEAR blends cells smoothly.
    return small.resize((width, height), Image.Resampling.BILINEAR)
