"""Load a room scan (LiDAR export: .glb/.gltf/.obj/.ply) or a video reconstruction (.npz) as points."""
from __future__ import annotations

from pathlib import Path

import numpy as np

MESH_EXT = {".glb", ".gltf", ".obj", ".ply", ".stl", ".off"}


def load_mesh_points(path: Path, n: int = 400_000):
    """Sample colored points from the scanned surfaces. Returns (points, colors uint8, up_hint)."""
    import trimesh

    scene = trimesh.load(str(path), force="scene")
    mesh = scene.dump(concatenate=True) if hasattr(scene, "dump") else scene
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("no surfaces found in the scan file")
    try:
        pts, _, colors = trimesh.sample.sample_surface(mesh, n, sample_color=True)
        colors = np.asarray(colors)[:, :3].astype(np.uint8)
    except Exception:
        pts, _ = trimesh.sample.sample_surface(mesh, n)
        colors = np.full((len(pts), 3), 180, np.uint8)
    # glTF and the iPhone scanner apps export Y-up; PLY/STL are often Z-up
    up = (0, 0, 1) if path.suffix.lower() in {".ply", ".stl"} else (0, 1, 0)
    return np.asarray(pts, np.float64), colors, np.array(up, float)


def load_recon(path: Path):
    """.npz written by recon_vggt.py: points, colors, cam_centers, cam_up."""
    z = np.load(path)
    return z["points"].astype(np.float64), z["colors"].astype(np.uint8), z["cam_up"].astype(float), z["cam_centers"]
