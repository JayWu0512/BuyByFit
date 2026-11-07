"""Room visualization endpoints -- owned by C (Isaac) per backend/WORKFLOW.md.

    POST /api/v1/rooms                              photo (+ pitch_deg) -> {room_id, scene}
    POST /api/v1/rooms/{room_id}/visualizations     {brief, products} -> 202 {job_id}
    GET  /api/v1/visualizations/{job_id}            progress, then the result
    POST /api/v1/rooms/{room_id}/visualizations/{job_id}/feedback   {verdict, issues, note} -> 201
    GET  /api/v1/rooms/{room_id}/files/{name}       photo / guide / render images

`products` are the search results the page already has (POST /api/v1/searches cards, flattened); the
service picks from them, places them at true size in the photo and renders the room restyled.
Contract: API_CONTRACT.md -> "Room visualization".
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.services.three_d import jobs, storage
from app.services.three_d.scene import scene_from_sensors

router = APIRouter(prefix="/api/v1", tags=["rooms"])

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1280
JOB_ID = re.compile(r"^[a-f0-9]{12}$")


@router.post("/rooms", status_code=201)
async def create_room(photo: UploadFile = File(...), pitch_deg: float | None = Form(default=None)):
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="photo must be 1 byte to 15 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="photo must be a JPEG or PNG image") from None
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    if pitch_deg is not None and not -60 <= pitch_deg <= 89:
        raise HTTPException(status_code=400, detail="pitch_deg must be between -60 and 89")

    room_id, _ = storage.new_room()
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    storage.save(room_id, "photo.jpg", buf.getvalue())
    scene = scene_from_sensors(*img.size, pitch_deg)
    storage.save(room_id, "scene.json", json.dumps(scene))
    return {"room_id": room_id, "scene": scene, "photo_url": storage.file_url(room_id, "photo.jpg")}


class ProductIn(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=80)
    width_cm: float = Field(gt=1, lt=1000)
    depth_cm: float = Field(gt=0, lt=1000)
    height_cm: float = Field(gt=0, lt=1000)
    image_url: str | None = Field(default=None, max_length=1000)
    product_url: str | None = Field(default=None, max_length=1000)


class VisualizationIn(BaseModel):
    brief: str = Field(min_length=1, max_length=600)
    products: list[ProductIn] = Field(min_length=1, max_length=30)


@router.post("/rooms/{room_id}/visualizations", status_code=202)
def create_visualization(room_id: str, body: VisualizationIn):
    if storage.room_dir(room_id) is None:
        raise HTTPException(status_code=404, detail="room not found")
    job_id = jobs.start(room_id, body.brief.strip(), [p.model_dump() for p in body.products])
    return {"job_id": job_id}


@router.get("/visualizations/{job_id}")
def get_visualization(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="visualization not found (the service may have restarted)")
    return JSONResponse(job, headers={"Cache-Control": "no-store"})


# What a person can flag on a restyle. Kept in sync with ISSUES in frontend/src/lib/rooms.ts.
Issue = Literal[
    "removed_existing",   # took out something already in the room (the bed, a wardrobe...)
    "missing_piece",      # something the brief needs isn't there (a bedroom with no bed)
    "floating",           # furniture not standing on the floor
    "wrong_size",         # a piece looks too big or too small for the room
    "wrong_product",      # doesn't look like the product we sell
    "wrong_orientation",  # facing a wall, back to the room, at an odd angle
    "blocks_path",        # in a doorway or walkway
    "room_changed",       # walls, windows, floor or framing redrawn
    "artifacts",          # glitches, leftover red boxes, text, melted shapes
    "off_brief",          # doesn't match the style that was asked for
    "unrealistic",        # fake-looking lighting, shadows or materials
]


class FeedbackIn(BaseModel):
    verdict: Literal["good", "bad"]
    issues: list[Issue] = Field(default_factory=list, max_length=11)
    note: str = Field(default="", max_length=500)


@router.post("/rooms/{room_id}/visualizations/{job_id}/feedback", status_code=201)
def create_feedback(room_id: str, job_id: str, body: FeedbackIn):
    """A person's verdict on one restyle (labels for the reviewer model). Sending again replaces it."""
    if not JOB_ID.match(job_id) or storage.room_file(room_id, f"render_{job_id}.png") is None:
        raise HTTPException(status_code=404, detail="visualization not found")
    record = {**body.model_dump(), "issues": sorted(set(body.issues)), "note": body.note.strip(),
              "job_id": job_id, "room_id": room_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    storage.save(room_id, f"feedback_{job_id}.json", json.dumps(record, indent=1))
    return {"ok": True}


@router.get("/rooms/{room_id}/files/{name}")
def get_room_file(room_id: str, name: str):
    path = storage.room_file(room_id, name)
    if path is None or path.suffix == ".json":
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})
