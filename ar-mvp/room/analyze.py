"""Point cloud of a room -> metric, floor-aligned room model the planner can reason about.

Steps: find the floor plane (RANSAC over near-horizontal planes) -> rotate so floor is y=0, up is +y
-> fix scale (LiDAR is already metres; video uses the phone's height above the floor, or a known width)
-> square the room up to its walls (min-area rectangle of the floor) -> 5 cm occupancy grid:
   floor we saw, things standing on it (existing furniture), and what's free.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from scipy.spatial import ConvexHull

CELL = 0.05             # metres per grid cell
WALL_BAND = 0.12        # points this close to the room edge are wall, not furniture
OBST_MIN_Y, OBST_MAX_Y = 0.06, 1.9
PHONE_HEIGHT = 1.40     # typical phone height above the floor while filming


@dataclass
class Room:
    width: float                      # x extent (m)
    depth: float                      # z extent (m)
    x0: float
    z0: float
    free: np.ndarray                  # bool grid [nz, nx]: floor seen and nothing on it
    seen: np.ndarray                  # bool grid: floor observed
    height: np.ndarray                # float grid: tallest thing in the cell (m), 0 if none
    transform: np.ndarray             # 4x4: raw scan coords -> room coords (metres)
    scale: float
    scale_source: str
    existing: list = field(default_factory=list)   # [{x, z, w, d, h, guess}]

    # grid helpers ---------------------------------------------------------
    def cell(self, x, z):
        return int((z - self.z0) / CELL), int((x - self.x0) / CELL)

    def walls(self) -> list[dict]:
        """4 walls, each with its inward normal and a point on it."""
        x0, z0, x1, z1 = self.x0, self.z0, self.x0 + self.width, self.z0 + self.depth
        return [
            {"name": "back", "a": (x0, z0), "b": (x1, z0), "normal": (0.0, 1.0), "length": self.width},
            {"name": "front", "a": (x1, z1), "b": (x0, z1), "normal": (0.0, -1.0), "length": self.width},
            {"name": "left", "a": (x0, z1), "b": (x0, z0), "normal": (1.0, 0.0), "length": self.depth},
            {"name": "right", "a": (x1, z0), "b": (x1, z1), "normal": (-1.0, 0.0), "length": self.depth},
        ]

    def to_json(self) -> dict:
        return {"width": round(self.width, 3), "depth": round(self.depth, 3), "x0": self.x0, "z0": self.z0,
                "cell": CELL, "scale": self.scale, "scale_source": self.scale_source,
                "transform": self.transform.round(6).tolist(),
                "free_ratio": round(float(self.free.sum()) / max(1, self.seen.sum()), 3),
                "existing": self.existing, "walls": self.walls()}


# ---------------------------------------------------------------- geometry
def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def find_floor(p: np.ndarray, up_hint: np.ndarray, iters: int = 600, seed: int = 0):
    """Lowest big near-horizontal plane. Returns (unit normal pointing up, offset d) with n.p + d = 0."""
    rng = np.random.default_rng(seed)
    up_hint = up_hint / np.linalg.norm(up_hint)
    extent = np.linalg.norm(np.percentile(p, 98, axis=0) - np.percentile(p, 2, axis=0))
    thr = 0.01 * extent
    sample = p[rng.choice(len(p), min(len(p), 60000), replace=False)]
    best, best_score = None, -1
    for _ in range(iters):
        a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        if np.dot(n, up_hint) < 0:
            n = -n
        if np.dot(n, up_hint) < 0.85:          # not horizontal enough
            continue
        d = -np.dot(n, a)
        dist = sample @ n + d
        inliers = np.abs(dist) < thr
        below = (dist < -3 * thr).mean()        # a floor has (almost) nothing under it
        score = inliers.sum() * (1.0 if below < 0.03 else 0.05)
        if score > best_score:
            best, best_score = (n, d), score
    if best is None:
        raise ValueError("couldn't find a floor plane")
    n, d = best                                  # refine with least squares on inliers
    inl = p[np.abs(p @ n + d) < thr]
    if len(inl) > 50:
        c = inl.mean(0)
        _, _, vt = np.linalg.svd(inl - c, full_matrices=False)
        n2 = vt[-1] * (1 if np.dot(vt[-1], n) > 0 else -1)
        n, d = n2, -np.dot(n2, c)
    return n, d


def min_area_rect_angle(xz: np.ndarray) -> float:
    """Angle that axis-aligns the minimum-area bounding rectangle of 2D points."""
    hull = xz[ConvexHull(xz).vertices]
    best, best_area = 0.0, np.inf
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        ang = -np.arctan2(e[1], e[0])
        c, s = np.cos(ang), np.sin(ang)
        r = xz @ np.array([[c, -s], [s, c]]).T
        area = np.ptp(r[:, 0]) * np.ptp(r[:, 1])
        if area < best_area:
            best, best_area = ang, area
    return best


# ---------------------------------------------------------------- main entry
def analyze(points: np.ndarray, *, source: str, up_hint=(0, 1, 0), cam_centers: np.ndarray | None = None,
            known_width: float | None = None) -> tuple[Room, np.ndarray]:
    """Returns the Room and the aligned points (same order as input)."""
    p = np.asarray(points, dtype=np.float64)
    n, d = find_floor(p, np.asarray(up_hint, float))

    # 1) level: floor normal -> +y, floor at y = 0
    R = _rotation_between(n, np.array([0.0, 1.0, 0.0]))
    t = np.array([0.0, d, 0.0])  # after rotation the plane is y + d = 0  ->  shift by +d
    q = p @ R.T + t
    cams = None if cam_centers is None else np.asarray(cam_centers, float) @ R.T + t

    # 2) metric scale
    scale, scale_source = 1.0, "lidar (metric)"
    floorish = q[np.abs(q[:, 1]) < 0.02 * np.ptp(q[:, 1]) + 1e-9]
    if source == "video":
        if known_width:
            ang0 = min_area_rect_angle(floorish[:, [0, 2]][:: max(1, len(floorish) // 20000)])
            c0, s0 = np.cos(ang0), np.sin(ang0)
            rx = floorish[:, [0, 2]] @ np.array([[c0, -s0], [s0, c0]]).T
            span = max(np.percentile(rx[:, 0], 99) - np.percentile(rx[:, 0], 1),
                       np.percentile(rx[:, 1], 99) - np.percentile(rx[:, 1], 1))
            scale, scale_source = known_width / span, f"room width you gave ({known_width} m)"
        elif cams is not None and np.median(cams[:, 1]) > 0:
            scale, scale_source = PHONE_HEIGHT / float(np.median(cams[:, 1])), f"phone held ~{PHONE_HEIGHT} m above the floor"
        else:
            scale_source = "unknown (no camera path); assumed metres"
    q *= scale
    floor_tol = 0.03
    floor_pts = q[np.abs(q[:, 1]) < floor_tol]
    if len(floor_pts) < 200:
        raise ValueError("too little floor visible to understand the room")

    # 3) square up to the walls
    ang = min_area_rect_angle(floor_pts[:: max(1, len(floor_pts) // 20000), [0, 2]])
    c, s = np.cos(ang), np.sin(ang)
    Ry = np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])   # rotates (x, z) by ang
    q = q @ Ry.T
    floor_pts = floor_pts @ Ry.T
    lo = np.percentile(floor_pts[:, [0, 2]], 1, axis=0)
    hi = np.percentile(floor_pts[:, [0, 2]], 99, axis=0)
    x0, z0 = float(lo[0]), float(lo[1])
    width, depth = float(hi[0] - lo[0]), float(hi[1] - lo[1])

    # 4) occupancy grid
    nx, nz = int(np.ceil(width / CELL)) + 1, int(np.ceil(depth / CELL)) + 1

    def grid_idx(pts):
        ix = ((pts[:, 0] - x0) / CELL).astype(int)
        iz = ((pts[:, 2] - z0) / CELL).astype(int)
        ok = (ix >= 0) & (ix < nx) & (iz >= 0) & (iz < nz)
        return iz[ok], ix[ok], ok

    seen = np.zeros((nz, nx), bool)
    floor_counts = np.zeros((nz, nx), int)
    iz, ix, _ = grid_idx(floor_pts)
    seen[iz, ix] = True
    np.add.at(floor_counts, (iz, ix), 1)
    pad = 4   # pad so closing doesn't eat the room's edge cells (that's where the walls are)
    seen = ndimage.binary_closing(np.pad(seen, pad), iterations=3)[pad:-pad, pad:-pad] | seen
    seen = ndimage.binary_fill_holes(seen)
    floor_density = float(np.median(floor_counts[floor_counts > 0])) if (floor_counts > 0).any() else 3.0

    inner = (q[:, 0] > x0 + WALL_BAND) & (q[:, 0] < x0 + width - WALL_BAND) & \
            (q[:, 2] > z0 + WALL_BAND) & (q[:, 2] < z0 + depth - WALL_BAND)
    stand = q[inner & (q[:, 1] > OBST_MIN_Y) & (q[:, 1] < OBST_MAX_Y)]
    counts = np.zeros((nz, nx), int)
    height = np.zeros((nz, nx))
    iz, ix, ok = grid_idx(stand)
    np.add.at(counts, (iz, ix), 1)
    np.maximum.at(height, (iz, ix), stand[ok, 1])
    # a cell holds furniture if it has a good fraction of the points a floor cell gets (scan-density relative)
    dense = counts >= max(2.0, 0.25 * floor_density)
    obstacle = ndimage.binary_opening(dense, iterations=1)
    obstacle = ndimage.binary_dilation(obstacle, iterations=1)
    height[~obstacle] = 0
    free = seen & ~obstacle

    # 5) existing furniture: connected blobs of obstacle
    existing = []
    lab, n_lab = ndimage.label(obstacle)
    for sl, k in zip(ndimage.find_objects(lab), range(1, n_lab + 1)):
        mask = lab[sl] == k
        if mask.sum() * CELL * CELL < 0.06:      # < 0.06 m^2: clutter
            continue
        h = float(height[sl][mask].max())
        w, dd = (sl[1].stop - sl[1].start) * CELL, (sl[0].stop - sl[0].start) * CELL
        cx, cz = x0 + (sl[1].start + sl[1].stop) / 2 * CELL, z0 + (sl[0].start + sl[0].stop) / 2 * CELL
        existing.append({"x": round(cx, 3), "z": round(cz, 3), "w": round(w, 2), "d": round(dd, 2),
                         "h": round(h, 2), "guess": guess_furniture(w, dd, h)})

    T = np.eye(4)
    T[:3, :3] = Ry @ (scale * R)
    T[:3, 3] = Ry @ (scale * t)
    room = Room(width, depth, x0, z0, free, seen, height, T, scale, scale_source, existing)
    return room, q


def guess_furniture(w: float, d: float, h: float) -> str:
    big, small = max(w, d), min(w, d)
    if 1.8 <= big <= 2.4 and 0.9 <= small <= 2.1 and 0.25 <= h <= 1.3:
        return "bed"
    if 1.4 <= big <= 3.2 and 0.7 <= small <= 1.1 and 0.6 <= h <= 1.1:
        return "sofa"
    if 0.9 <= big <= 2.0 and 0.45 <= small <= 0.9 and 0.65 <= h <= 0.85:
        return "desk or table"
    if h >= 1.3 and small <= 0.6:
        return "shelf or wardrobe"
    if big <= 1.0 and 0.7 <= h <= 1.2:
        return "chair"
    return "object"
