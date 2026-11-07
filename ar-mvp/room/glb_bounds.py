"""Bounding box of a .glb without loading geometry: glTF requires POSITION accessors to carry min/max,
even when the mesh is Draco-compressed, so we only need the JSON chunk and the node transforms."""
from __future__ import annotations

import json
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T     # glTF is column-major
    m = np.eye(4)
    if "scale" in node:
        m = np.diag([*node["scale"], 1.0]) @ m
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        rm = np.eye(4)
        rm[:3, :3] = r
        m = rm @ m
    if "translation" in node:
        tm = np.eye(4)
        tm[:3, 3] = node["translation"]
        m = tm @ m
    return m


@lru_cache(maxsize=1024)
def glb_size(path: str) -> tuple[float, float, float] | None:
    """(x, y, z) extent in model units (metres for our catalog), or None if unreadable."""
    try:
        data = Path(path).read_bytes()
        magic, _, _ = struct.unpack_from("<III", data, 0)
        if magic != 0x46546C67:          # 'glTF'
            return None
        clen, ctype = struct.unpack_from("<II", data, 12)
        gltf = json.loads(data[20:20 + clen])
    except (OSError, struct.error, ValueError):
        return None
    nodes, meshes, acc = gltf.get("nodes", []), gltf.get("meshes", []), gltf.get("accessors", [])
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)

    def visit(i: int, parent: np.ndarray):
        nonlocal lo, hi
        node = nodes[i]
        m = parent @ _node_matrix(node)
        if "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                a = acc[prim["attributes"]["POSITION"]] if "POSITION" in prim.get("attributes", {}) else None
                if not a or "min" not in a:
                    continue
                mn, mx = a["min"], a["max"]
                corners = np.array([[x, y, z, 1] for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])])
                w = corners @ m.T
                lo, hi = np.minimum(lo, w[:, :3].min(0)), np.maximum(hi, w[:, :3].max(0))
        for c in node.get("children", []):
            visit(c, m)

    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)] if gltf.get("scenes") else {"nodes": range(len(nodes))}
    for r in scene.get("nodes", []):
        visit(r, np.eye(4))
    if not np.isfinite(lo).all():
        return None
    return tuple(float(v) for v in (hi - lo))
