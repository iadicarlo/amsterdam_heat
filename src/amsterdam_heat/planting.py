"""Where new street trees add the most shade on walking areas.

Follows the greedy search of TreePlanter (Wallenberg et al. 2022): trees are added
one at a time, each where it shades the most walking area that is still in the sun.
On flat ground a tree's shadow at a given sun position is a fixed shape, the crown
cylinder (from a quarter of the tree height, SOLWEIG's trunk zone, to the top)
swept along the shadow direction, so the gain of every candidate can be counted
exactly on the 1 m grid without rerunning the physics. Shade counted this way only
grows as trees are added and each tree's gain can only shrink, the coverage case in
which greedy selection is near optimal (Nemhauser et al. 1978). The chosen set is
then checked with a full SOLWEIG run (scripts/verify_trees.py).

Candidates are points on public pavement or public green, away from facades, from
existing crowns and from the carriageway. Cables and pipes are not in open data,
so every spot needs the city's own check.
"""

import heapq
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.ndimage import binary_dilation, distance_transform_edt


@dataclass(frozen=True)
class TreeSpec:
    height: float = 12.0  # m, a medium street tree after about 15 to 20 years
    crown_radius: float = 4.0  # m
    trunk_fraction: float = 0.25  # SOLWEIG's trunk zone


@dataclass(frozen=True)
class Rules:
    facade: float = 4.0  # m from a building
    crown: float = 5.0  # m from an existing tree canopy pixel
    edge: float = 1.0  # m inside the pavement or green, away from road and parking
    spacing: float = 8.0  # m between new trees
    grid: int = 2  # candidate every n metres


def shadow_offsets(tree: TreeSpec, altitude: float, azimuth: float, res: float = 1.0) -> np.ndarray:
    """(row, col) offsets from the trunk of the pixels a tree shades on flat ground.
    ``altitude`` and ``azimuth`` in degrees, azimuth clockwise from north."""
    alt, az = np.radians(altitude), np.radians(azimuth)
    r = int(np.ceil(tree.crown_radius / res))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = np.column_stack([yy[(xx**2 + yy**2) * res**2 <= tree.crown_radius**2],
                            xx[(xx**2 + yy**2) * res**2 <= tree.crown_radius**2]])
    offsets = set()
    for z in np.linspace(tree.trunk_fraction * tree.height, tree.height, 25):
        reach = z / np.tan(alt) / res
        dx, dy = -reach * np.sin(az), -reach * np.cos(az)  # away from the sun, east and north
        shift = np.array([-dy, dx])  # rows grow southwards
        for p in np.rint(disk + shift).astype(int):
            offsets.add((int(p[0]), int(p[1])))
    return np.array(sorted(offsets))


def crown_offsets(tree: TreeSpec, res: float = 1.0) -> np.ndarray:
    r = int(np.ceil(tree.crown_radius / res))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    keep = (xx**2 + yy**2) * res**2 <= tree.crown_radius**2
    return np.column_stack([yy[keep], xx[keep]])


def candidates(plantable: np.ndarray, buildings: np.ndarray, canopy: np.ndarray,
               rules: Rules | None = None, res: float = 1.0) -> np.ndarray:
    """(row, col) of candidate trunks: inside ``plantable`` by ``rules.edge``, and far
    enough from buildings and existing canopy."""
    rules = rules or Rules()
    inside = distance_transform_edt(plantable) * res >= rules.edge
    off_facade = distance_transform_edt(~buildings) * res >= rules.facade
    off_crowns = distance_transform_edt(~canopy) * res >= rules.crown
    ok = inside & off_facade & off_crowns
    grid = np.zeros_like(ok)
    grid[::rules.grid, ::rules.grid] = True
    return np.argwhere(ok & grid)


def footprint_patch(tree: TreeSpec, altitude: float, azimuth: float, radius: int, res: float = 1.0) -> np.ndarray:
    """Boolean (2 radius + 1) square centred on the trunk, True where the tree shades."""
    patch = np.zeros((2 * radius + 1, 2 * radius + 1), bool)
    o = shadow_offsets(tree, altitude, azimuth, res) + radius
    ok = (o >= 0).all(axis=1) & (o <= 2 * radius).all(axis=1)
    patch[o[ok, 0], o[ok, 1]] = True
    return patch


class Shade:
    """Shade on the grid as SOLWEIG reports it for the guidelines: for each hour the two
    hourly bands around it (sun at h-0:30 and h+0:30), shaded where their mean is below
    0.5. A new crown sets a band to the canopy transmissivity where it falls."""

    TRANSMISSIVITY = 0.03

    def __init__(self, bands: dict, patches: dict, weight: np.ndarray, hour_weight: dict):
        self.bands = {h: (a.copy(), b.copy()) for h, (a, b) in bands.items()}
        self.patches = patches  # hour -> (patch at h-0:30, patch at h+0:30)
        self.weight, self.hour_weight = weight, hour_weight
        self.radius = next(iter(patches.values()))[0].shape[0] // 2

    def _window(self, rc):
        r, c, k = int(rc[0]), int(rc[1]), self.radius
        h, w = self.weight.shape
        r0, r1, c0, c1 = max(r - k, 0), min(r + k + 1, h), max(c - k, 0), min(c + k + 1, w)
        return (slice(r0, r1), slice(c0, c1)), (slice(r0 - r + k, r1 - r + k), slice(c0 - c + k, c1 - c + k))

    def shaded(self, h) -> np.ndarray:
        a, b = self.bands[h]
        return 0.5 * (a + b) < 0.5

    def gain(self, rc) -> float:
        g, (grid, pw) = 0.0, self._window(rc)
        for h, wh in self.hour_weight.items():
            a, b = (x[grid] for x in self.bands[h])
            pa, pb = (p[pw] for p in self.patches[h])
            na = np.where(pa, np.minimum(a, self.TRANSMISSIVITY), a)
            nb = np.where(pb, np.minimum(b, self.TRANSMISSIVITY), b)
            new = (0.5 * (na + nb) < 0.5) & ~(0.5 * (a + b) < 0.5)
            g += wh * self.weight[grid][new].sum()
        return float(g)

    def add(self, rc) -> None:
        grid, pw = self._window(rc)
        for h in self.hour_weight:
            for x, p in zip(self.bands[h], self.patches[h], strict=True):
                x[grid] = np.where(p[pw], np.minimum(x[grid], self.TRANSMISSIVITY), x[grid])


def greedy(cands: np.ndarray, shade: Shade, n_max: int, spacing: float, stop=None,
           res: float = 1.0) -> pd.DataFrame:
    """Add trees one at a time where they shade the most weighted walking area still in
    the sun (``shade`` holds the state and is updated). ``stop(shade)`` may end the
    search early. Returns the chosen trees in order."""
    alive = np.ones(len(cands), bool)
    # lazy greedy: gains only shrink, so a refreshed gain that still tops the heap is exact
    heap = [(-shade.gain(c), i) for i, c in enumerate(cands)]
    heapq.heapify(heap)
    chosen = []
    spacing_px = spacing / res
    while heap and len(chosen) < n_max:
        _, i = heapq.heappop(heap)
        if not alive[i]:
            continue
        g = shade.gain(cands[i])
        if g <= 0:
            continue
        if heap and g < -heap[0][0]:
            heapq.heappush(heap, (-g, i))
            continue
        shade.add(cands[i])
        chosen.append({"row": int(cands[i][0]), "col": int(cands[i][1]), "gain": g})
        alive[np.hypot(*(cands - cands[i]).T) < spacing_px] = False
        if stop is not None and stop(shade):
            break
    return pd.DataFrame(chosen)


def burn(trees: np.ndarray, rows, cols, tree: TreeSpec, res: float = 1.0) -> np.ndarray:
    """Tree height raster with new crowns added (existing taller vegetation kept)."""
    out = trees.copy()
    for o in crown_offsets(tree, res):
        r, c = np.asarray(rows) + o[0], np.asarray(cols) + o[1]
        ok = (r >= 0) & (r < out.shape[0]) & (c >= 0) & (c < out.shape[1])
        out[r[ok], c[ok]] = np.maximum(out[r[ok], c[ok]], tree.height)
    return out


def edge_ring(mask: np.ndarray) -> np.ndarray:
    return binary_dilation(mask) & ~mask
