"""A colored synthetic room (4.6 x 3.8 m, wood floor, an existing bed) so the viewer can be tried without a scan."""
from __future__ import annotations

import numpy as np


def demo_points(seed: int = 7, with_bed: bool = False):
    rng = np.random.default_rng(seed)
    W, D, H = 4.6, 3.8, 2.6
    pts, cols = [], []

    def add(p, base, jitter=12):
        c = np.clip(np.array(base) + rng.normal(0, jitter, (len(p), 3)), 0, 255)
        pts.append(p)
        cols.append(c.astype(np.uint8))

    n = 140_000
    floor = np.c_[rng.random(n) * W, np.zeros(n), rng.random(n) * D]
    plank = ((floor[:, 2] / 0.18).astype(int) % 2) * 14                       # wood planks
    add(floor, [150, 112, 78], 10)
    cols[-1] = np.clip(cols[-1].astype(int) - plank[:, None], 0, 255).astype(np.uint8)
    m = 120_000
    u, v, side = rng.random(m), rng.random(m) * H, rng.integers(0, 4, m)
    walls = np.select([side[:, None] == k for k in range(4)],
                      [np.c_[u * W, v, np.zeros(m)], np.c_[u * W, v, np.full(m, D)],
                       np.c_[np.zeros(m), v, u * D], np.c_[np.full(m, W), v, u * D]])
    add(walls, [226, 222, 214], 6)
    win = (side == 1) & (np.abs(u * W - 2.3) < 0.7) & (v > 0.9) & (v < 2.1)      # a window
    cols[-1][win] = [170, 200, 225]
    if with_bed:
        k = 40_000
        f, a, b = rng.integers(0, 5, k), rng.random(k), rng.random(k)
        x0, x1, z0, z1, h = W / 2 - 0.8, W / 2 + 0.8, 0.0, 2.05, 0.55
        bed = np.select([f[:, None] == i for i in range(5)],
                        [np.c_[x0 + a * 1.6, np.full(k, h), z0 + b * 2.05], np.c_[np.full(k, x0), a * h, z0 + b * 2.05],
                         np.c_[np.full(k, x1), a * h, z0 + b * 2.05], np.c_[x0 + a * 1.6, b * h, np.full(k, z1)],
                         np.c_[x0 + a * 1.6, b * h, np.full(k, z0 + 0.01)]])
        add(bed, [86, 104, 140], 10)
    p = np.vstack(pts) + rng.normal(0, 0.004, (sum(len(x) for x in pts), 3))
    return p, np.vstack(cols)
