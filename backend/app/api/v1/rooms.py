"""Room visualization endpoints -- owned by C (Isaac) per backend/WORKFLOW.md.

    POST /api/v1/rooms                              photo (+ pitch_deg) -> {room_id, scene}
    POST /api/v1/rooms/{room_id}/visualizations     {brief, products} -> 202 {job_id}
    GET  /api/v1/visualizations/{job_id}            progress, then the result
    GET  /api/v1/rooms/{room_id}/files/{name}       photo / guide / render images

`products` are the search results the page already has (POST /api/v1/searches cards, flattened); the
service picks from them, places them at true size in the photo and renders the room restyled.
Contract: API_CONTRACT.md -> "Room visualization".
"""

from __future__ import annotations

import io
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.services.three_d import jobs, storage
from app.services.three_d.scene import scene_from_sensors

router = APIRouter(prefix="/api/v1", tags=["rooms"])

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1280


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

    room_id, folder = storage.new_room()
    img.save(folder / "photo.jpg", "JPEG", quality=90)
    scene = scene_from_sensors(*img.size, pitch_deg)
    (folder / "scene.json").write_text(json.dumps(scene))
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


@router.get("/rooms/{room_id}/files/{name}")
def get_room_file(room_id: str, name: str):
    path = storage.room_file(room_id, name)
    if path is None or path.suffix == ".json":
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})
