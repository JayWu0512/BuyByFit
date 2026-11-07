"""Where room photos and renders live.

Every file is written to a local folder (backend/storage/rooms, gitignored, override with THREE_D_STORAGE_DIR)
and, when THREE_D_BUCKET is set, also to Cloud Storage at gs://<bucket>/rooms/<room_id>/<name>. Cloud Run's
disk is wiped on every restart, so the bucket is what keeps results (and the run traces + user feedback the
reviewer model is trained on). A file missing locally is fetched back from the bucket on first use.
Without THREE_D_BUCKET (local dev, tests) it is local-only, as before.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import urllib.parse
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(os.environ.get("THREE_D_STORAGE_DIR") or Path(__file__).resolve().parents[3] / "storage" / "rooms")
BUCKET = os.environ.get("THREE_D_BUCKET", "").strip()
ROOM_ID = re.compile(r"^[a-f0-9]{32}$")
FILE_NAME = re.compile(r"^[a-z0-9_]{1,40}\.(jpg|png|json)$")
TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".json": "application/json"}

_session = None
_lock = threading.Lock()


# ---------------------------------------------------------------- Cloud Storage (JSON API, no extra dependency)

def _gcs():
    global _session
    with _lock:
        if _session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
            _session = AuthorizedSession(creds)
    return _session


def _object(room_id: str, name: str) -> str:
    return urllib.parse.quote(f"rooms/{room_id}/{name}", safe="")


def _upload(room_id: str, name: str, data: bytes) -> None:
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o"
    r = _gcs().post(url, params={"uploadType": "media", "name": f"rooms/{room_id}/{name}"}, data=data,
                    headers={"Content-Type": TYPES[Path(name).suffix]}, timeout=30)
    r.raise_for_status()


def _download(room_id: str, name: str) -> bytes | None:
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{_object(room_id, name)}"
    try:
        r = _gcs().get(url, params={"alt": "media"}, timeout=30)
    except Exception:
        log.exception("bucket read failed: %s/%s", room_id, name)
        return None
    if r.status_code == 404:
        return None
    if not r.ok:
        log.error("bucket read %s/%s: HTTP %s", room_id, name, r.status_code)
        return None
    return r.content


# ---------------------------------------------------------------- rooms and files

def new_room() -> tuple[str, Path]:
    room_id = uuid.uuid4().hex
    folder = ROOT / room_id
    folder.mkdir(parents=True)
    return room_id, folder


def save(room_id: str, name: str, data: bytes | str) -> Path:
    """Write a room file locally and to the bucket. A bucket failure is logged, never fails the user's run."""
    if not ROOM_ID.match(room_id) or not FILE_NAME.match(name):
        raise ValueError(f"bad room file name: {room_id}/{name}")
    raw = data.encode() if isinstance(data, str) else data
    folder = ROOT / room_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(raw)
    if BUCKET:
        try:
            _upload(room_id, name, raw)
        except Exception:
            log.exception("bucket write failed: %s/%s", room_id, name)
    return path


def _restore(room_id: str, name: str) -> Path | None:
    """Fetch one file back from the bucket into the local folder (after a restart)."""
    if not BUCKET:
        return None
    data = _download(room_id, name)
    if data is None:
        return None
    folder = ROOT / room_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def room_dir(room_id: str) -> Path | None:
    if not ROOM_ID.match(room_id or ""):
        return None
    folder = ROOT / room_id
    if (folder / "photo.jpg").is_file():
        return folder
    # A room made before a restart: bring back what a new run needs.
    if _restore(room_id, "photo.jpg") and _restore(room_id, "scene.json"):
        return folder
    return None


def room_file(room_id: str, name: str) -> Path | None:
    if not ROOM_ID.match(room_id or "") or not FILE_NAME.match(name or ""):
        return None
    path = ROOT / room_id / name
    if path.is_file():
        return path
    return _restore(room_id, name)


def file_url(room_id: str, name: str) -> str:
    """Public path (same on the FastAPI service and through the Next.js proxy)."""
    return f"/api/v1/rooms/{room_id}/files/{name}"
