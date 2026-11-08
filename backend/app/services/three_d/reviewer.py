"""Design review of a restyled room by our fine-tuned taste model (Inkling 2 Small, LoRA-tuned on Tinker).

    review = review_render(png_bytes)   # {"overall", "scores", "issues", "fixes", "verdict"} or None

Config (both required, else the review is skipped and the restyle works as before):
    TASTE_REVIEWER_MODEL   tinker://<run>/sampler_weights/<step>   (from taste/data/runs/*/checkpoints.jsonl)
    TINKER_API_KEY         Tinker API key (keep it in Secret Manager on Cloud Run)
Calls Tinker's OpenAI-compatible endpoint with plain HTTP. Never raises: a slow or failed review returns None.
The prompt must match the one the model was trained on (taste/student.py REVIEW_PROMPT).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re

import requests
from PIL import Image

log = logging.getLogger(__name__)

TINKER_OAI = os.environ.get("TINKER_OAI_URL",
                            "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1").rstrip("/")
PRINCIPLES = ["scale", "layout", "focal_point", "lighting", "palette", "restraint", "cohesion", "realism"]
# Same text as taste/student.py REVIEW_PROMPT: the fine-tuned model expects exactly this.
REVIEW_PROMPT = (
    "You are an interior design reviewer. Judge this room's DESIGN (not the photo). Reply with JSON: "
    '{"overall": 1-10, "scores": {' + ", ".join(f'"{p}": 1-5' for p in PRINCIPLES) + '}, '
    '"issues": [...], "fixes": [...], "verdict": "..."}'
)
IMAGE_SIDE = 1024
TIMEOUT_S = 45


def configured() -> bool:
    return bool(os.environ.get("TASTE_REVIEWER_MODEL") and os.environ.get("TINKER_API_KEY"))


def _jpeg_data_uri(image: bytes) -> str:
    im = Image.open(io.BytesIO(image)).convert("RGB")
    im.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def clean(raw: dict) -> dict | None:
    """Keep only well-formed fields; None if there's no usable overall score."""
    try:
        overall = int(raw.get("overall"))
    except (TypeError, ValueError):
        return None
    if not 1 <= overall <= 10:
        return None
    scores = {}
    for p in PRINCIPLES:
        try:
            v = int((raw.get("scores") or {}).get(p))
        except (TypeError, ValueError):
            continue
        if 1 <= v <= 5:
            scores[p] = v
    texts = lambda key: [str(x).strip()[:300] for x in (raw.get(key) or []) if str(x).strip()][:3]  # noqa: E731
    return {"overall": overall, "scores": scores, "issues": texts("issues"), "fixes": texts("fixes"),
            "verdict": str(raw.get("verdict") or "").strip()[:400]}


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return clean(json.loads(m.group(0)))
    except (json.JSONDecodeError, AttributeError):
        return None


# Styling ideas for the user: same trained reply format (so the fine-tuned model stays on familiar ground); the
# pipeline shows only its "fixes", phrased as styling details rather than critique or shopping.
STYLE_PROMPT = REVIEW_PROMPT + (
    ' Put in "fixes" up to 3 short expert notes critiquing the STYLE only, the way a senior interior designer '
    "would: palette, materials and finishes, textures, lighting mood, cohesion and balance of the look, each with "
    "a concrete styling move. The furniture is final: never suggest changing, selecting, replacing, adding or "
    "buying furniture, seating or any product. Do not comment on image quality, rendering, realism, scale, size, "
    "placement, the camera, or any drawn rectangles or numbers."
)
# Backstop for the "no product recommendations" rule (the pipeline also drops any idea naming furniture).
_NEW_THING = re.compile(r"\b(buy|buying|purchase|shop|replace|replacing|swap|select|choose|seating|furniture|"
                        r"new (?:sofa|bed|chair|table|desk))\b", re.I)


# The designer's brief: the expert critiques the user's room as it is now, before the restyle is designed.
ROOM_PROMPT = REVIEW_PROMPT + (
    ' This is the room BEFORE a restyle. In "issues" give up to 2 expert notes on what in its current style does '
    'not work, and in "fixes" up to 2 style directions a designer should take: palette, materials and finishes, '
    "textures, lighting mood, cohesion and balance of the look. Do not comment on image quality, the camera or the "
    "photo itself, and do not name brands or products to buy."
)


def room_notes(photo: bytes) -> list[str]:
    """Up to 4 expert style notes on the room as photographed (what doesn't work, then where to take it); [] if
    none or the call failed. They brief the designer, they aren't shown to the user."""
    review = review_render(photo, ROOM_PROMPT)
    if not review:
        return []
    return [n for n in review["issues"][:2] + review["fixes"][:2] if not re.search(r"\b(buy|purchase|shop)\b", n, re.I)]


def style_suggestions(image: bytes) -> list[str]:
    """Up to 3 styling ideas (no products to buy) for a finished render; [] if none or the call failed."""
    review = review_render(image, STYLE_PROMPT)
    fixes = (review or {}).get("fixes") or []
    return [f for f in fixes if not _NEW_THING.search(f)]


def review_render(image: bytes, prompt: str = REVIEW_PROMPT) -> dict | None:
    if not configured():
        return None
    body = {
        "model": os.environ["TASTE_REVIEWER_MODEL"],
        "max_tokens": 1200,
        "temperature": 0.0,
        "reasoning_effort": "low",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": _jpeg_data_uri(image)}},
            {"type": "text", "text": prompt}]}],
    }
    try:
        r = requests.post(f"{TINKER_OAI}/chat/completions", json=body, timeout=TIMEOUT_S,
                          headers={"Authorization": f"Bearer {os.environ['TINKER_API_KEY']}"})
        if not r.ok:
            log.warning("design review: HTTP %s %s", r.status_code, r.text[:200])
            return None
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception:
        log.exception("design review failed")
        return None
    review = parse(content)
    if review is None:
        log.warning("design review: unparseable reply %r", content[:200])
    return review
