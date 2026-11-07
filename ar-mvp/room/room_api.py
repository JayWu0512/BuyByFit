"""/api/room/*: upload a scan or video -> background job -> room model -> vibe plan."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import traceback
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from analyze import analyze
from demo_room import demo_points
from ingest import MESH_EXT, load_mesh_points, load_recon
from planner import TEMPLATES, Planner

ROOMS = Path.home() / "buybyfit-data" / "rooms"
VGGT_PY = Path.home() / "buybyfit-data" / "vggt-venv" / "Scripts" / "python.exe"
RECON = Path(__file__).with_name("recon_vggt.py")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MAX_POINTS = 250_000

router = APIRouter()
jobs: dict[str, dict] = {}
search_fn = None          # set by server.py: (query, types, max_w, max_d, max_h, k) -> rows


def _set(rid, **kw):
    jobs.setdefault(rid, {}).update(kw)
    (ROOMS / rid / "status.json").write_text(json.dumps(jobs[rid]), encoding="utf-8")


def _save_points(rid: str, q: np.ndarray, colors: np.ndarray):
    idx = np.random.default_rng(0).choice(len(q), min(len(q), MAX_POINTS), replace=False)
    xyz = q[idx].astype(np.float32)
    rgb = colors[idx].astype(np.uint8)
    (ROOMS / rid / "points.bin").write_bytes(np.int32(len(idx)).tobytes() + xyz.tobytes() + rgb.tobytes())


def _process(rid: str, path: Path | None, known_width: float | None, demo: str | None = None):
    d = ROOMS / rid
    try:
        mesh_url = None
        if demo:
            _set(rid, status="analyzing", message="Building the demo room…")
            pts, cols = demo_points(with_bed=(demo == "bedroom"))
            room, q = analyze(pts, source="lidar")
        elif path.suffix.lower() in VIDEO_EXT:
            if not VGGT_PY.exists():
                raise RuntimeError("Video reconstruction isn't set up on this laptop yet. Run "
                                   "ar-mvp\\room\\setup_video_recon.ps1 once, or upload a LiDAR scan (.glb/.obj).")
            _set(rid, status="reconstructing", message="Rebuilding your room in 3D from the video (about a minute)…")
            out = d / "recon.npz"
            r = subprocess.run([str(VGGT_PY), str(RECON), str(path), str(out)], capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                raise RuntimeError("3D reconstruction failed: " + (r.stderr or r.stdout).strip().splitlines()[-1][:300])
            pts, cols, up, cams = load_recon(out)
            _set(rid, status="analyzing", message="Finding the floor, walls and free space…")
            room, q = analyze(pts, source="video", up_hint=up, cam_centers=cams, known_width=known_width)
        else:
            _set(rid, status="analyzing", message="Reading your scan and finding the floor, walls and free space…")
            pts, cols, up = load_mesh_points(path)
            try:
                room, q = analyze(pts, source="lidar", up_hint=up, known_width=None)
            except ValueError:   # some apps export Z-up
                room, q = analyze(pts, source="lidar", up_hint=np.array([0, 0, 1.0]) if up[1] else np.array([0, 1.0, 0]))
            if path.suffix.lower() in {".glb", ".gltf"}:
                mesh_url = f"/rooms/{rid}/{path.name}"
            else:
                import trimesh
                trimesh.load(str(path), force="scene").export(str(d / "scan.glb"))
                mesh_url = f"/rooms/{rid}/scan.glb"
        _save_points(rid, q, cols)
        np.savez_compressed(d / "grid.npz", free=room.free, seen=room.seen, height=room.height)
        info = room.to_json()
        (d / "room.json").write_text(json.dumps(info), encoding="utf-8")
        _set(rid, status="ready", message=f"Room is {room.width:.1f} × {room.depth:.1f} m "
             f"({room.scale_source}). Found {len(room.existing)} existing piece(s).",
             room=info, points_url=f"/rooms/{rid}/points.bin", mesh_url=mesh_url)
    except Exception as e:
        traceback.print_exc()
        _set(rid, status="error", message=str(e))


def _start(path, known_width, demo=None) -> str:
    rid = uuid.uuid4().hex[:10]
    (ROOMS / rid).mkdir(parents=True, exist_ok=True)
    if path is not None:
        dest = ROOMS / rid / f"input{path[1].suffix.lower()}"
        with dest.open("wb") as f:
            shutil.copyfileobj(path[0], f)
        path = dest
    _set(rid, status="queued", message="Queued…")
    threading.Thread(target=_process, args=(rid, path, known_width, demo), daemon=True).start()
    return rid


@router.post("/api/room/upload")
async def upload(file: UploadFile = File(...), known_width: float | None = Form(None)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT | MESH_EXT:
        raise HTTPException(400, f"Upload a phone video ({', '.join(sorted(VIDEO_EXT))}) or a LiDAR scan "
                                 f"({', '.join(sorted(MESH_EXT))}). For a .usdz, export GLB/OBJ from the scanner app.")
    return {"id": _start((file.file, Path(file.filename)), known_width)}


@router.post("/api/room/demo")
def demo(kind: str = "living"):
    return {"id": _start(None, None, demo="bedroom" if kind == "bedroom" else "living")}


def _job(rid: str) -> dict:
    if rid not in jobs:
        f = ROOMS / rid / "status.json"
        if not f.exists():
            raise HTTPException(404, "no such room")
        jobs[rid] = json.loads(f.read_text(encoding="utf-8"))
    return jobs[rid]


@router.get("/api/room/{rid}")
def status(rid: str):
    return _job(rid)


class PlanIn(BaseModel):
    vibe: str
    room_type: str | None = None


@router.post("/api/room/{rid}/plan")
def plan(rid: str, body: PlanIn):
    job = _job(rid)
    if job.get("status") != "ready":
        raise HTTPException(409, "room isn't ready yet")
    from analyze import Room
    info, g = job["room"], np.load(ROOMS / rid / "grid.npz")
    room = Room(info["width"], info["depth"], info["x0"], info["z0"], g["free"], g["seen"], g["height"],
                np.array(info["transform"]), info["scale"], info["scale_source"], info["existing"])
    rtype = body.room_type if body.room_type in TEMPLATES else None
    result = Planner(room, body.vibe, search_fn, rtype).plan()
    (ROOMS / rid / "plan.json").write_text(json.dumps(result), encoding="utf-8")
    return result


@router.get("/rooms/{rid}/{name}")
def room_file(rid: str, name: str):
    f = (ROOMS / rid / name).resolve()
    if ROOMS.resolve() not in f.parents or not f.is_file() or name.startswith("status"):
        raise HTTPException(404)
    return FileResponse(f)
