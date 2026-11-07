"""Small wrappers around @gltf-transform/cli (needs Node / npx on PATH)."""
from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path

_CLI = "npx --yes @gltf-transform/cli@4"


def optimize_glb(src: Path, dst: Path, texture_size: int = 1024) -> None:
    """Phone-friendly copy: textures resized to <= texture_size, Draco-compressed geometry."""
    subprocess.run(
        f'{_CLI} optimize "{src}" "{dst}" --compress draco --texture-compress auto --texture-size {texture_size}',
        shell=True, check=True, capture_output=True, timeout=900,
    )


def glb_bbox(path: Path) -> tuple[float, float, float]:
    """(x, y, z) extent of the default scene in model units (glTF says metres, Y up)."""
    env = {**os.environ, "NO_COLOR": "1"}
    out = subprocess.run(f'{_CLI} inspect "{path}" --format csv', shell=True, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env, timeout=300).stdout
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("#,name,rootName,bboxMin"))
    row = next(csv.DictReader(io.StringIO("\n".join(lines[start:start + 2]))))
    lo = [float(v) for v in row["bboxMin"].split(",")]
    hi = [float(v) for v in row["bboxMax"].split(",")]
    return tuple(round(h - l, 4) for l, h in zip(lo, hi))
