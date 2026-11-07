"""Where room photos and renders live.

Hackathon: a local folder (backend/storage/rooms, gitignored, override with THREE_D_STORAGE_DIR).
The team rule is "no generated binaries on the backend", so before production this should become a
Supabase Storage bucket; only this module needs to change.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("THREE_D_STORAGE_DIR") or Path(__file__).resolve().parents[3] / "storage" / "rooms")
ROOM_ID = re.compile(r"^[a-f0-9]{32}$")
FILE_NAME = re.compile(r"^[a-z0-9_]{1,40}\.(jpg|png|json)$")


def new_room() -> tuple[str, Path]:
    room_id = uuid.uuid4().hex
    folder = ROOT / room_id
    folder.mkdir(parents=True)
    return room_id, folder


def room_dir(room_id: str) -> Path | None:
    if not ROOM_ID.match(room_id or ""):
        return None
    folder = ROOT / room_id
    return folder if folder.is_dir() else None


def room_file(room_id: str, name: str) -> Path | None:
    folder = room_dir(room_id)
    if folder is None or not FILE_NAME.match(name or ""):
        return None
    path = folder / name
    return path if path.is_file() else None


def file_url(room_id: str, name: str) -> str:
    """Public path (same on the FastAPI service and through the Next.js proxy)."""
    return f"/api/v1/rooms/{room_id}/files/{name}"
