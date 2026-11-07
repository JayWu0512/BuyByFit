"""Search/recommendation endpoints -- owned by B per backend/WORKFLOW.md.

Implements the documented contract (API_CONTRACT.md, MOCK_API.md) backed by
the real `recommend()` pipeline instead of the mock's tag-overlap scorer.
Search state is kept in-memory, same as mock_server.py, since there is no
persisted `searches` table yet (that would be a new entity in
`app/db/relational.py`, requiring Diwas/Isaac review).

Product and room-media fields still need Diwas/Isaac sign-off before this
fully replaces mock_server.py as the frontend contract.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.services.logic.recommend import recommend

router = APIRouter(prefix="/api/v1", tags=["searches"])

_SEARCHES: dict[str, dict[str, Any]] = {}


def _coerce_number(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"{field} must be a number") from error


def _normalize_filters(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="filters must be an object")

    categories = raw.get("categories", [])
    colors = raw.get("colors", [])
    if isinstance(categories, str):
        categories = [categories]
    if isinstance(colors, str):
        colors = [colors]
    if not isinstance(categories, list) or not isinstance(colors, list):
        raise HTTPException(status_code=400, detail="categories and colors must be arrays")

    return {
        "categories": [str(item).lower() for item in categories],
        "colors": [str(item).lower() for item in colors],
        "min_price": _coerce_number(raw.get("min_price"), "filters.min_price"),
        "max_price": _coerce_number(raw.get("max_price"), "filters.max_price"),
        "max_width_cm": _coerce_number(raw.get("max_width_cm"), "filters.max_width_cm"),
        "max_depth_cm": _coerce_number(raw.get("max_depth_cm"), "filters.max_depth_cm"),
    }


def _paginate(results: list[dict[str, Any]], page: int, per_page: int) -> dict[str, Any]:
    total = len(results)
    start = (page - 1) * per_page
    return {
        "products": results[start : start + per_page],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    }


async def _read_request_payload(request: Request) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    """Parse JSON or multipart body into (filters, style_description, media)."""
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_filters_field = form.get("filters", "{}") or "{}"
        if isinstance(raw_filters_field, UploadFile):
            raise HTTPException(status_code=400, detail="filters must be a text field, not a file")
        try:
            raw_filters = json.loads(raw_filters_field)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="multipart filters field must contain valid JSON") from error

        style_field = form.get("style_description", "")
        style_description = "" if isinstance(style_field, UploadFile) else str(style_field).strip()

        media: dict[str, Any] | None = None
        upload = form.get("media")
        if isinstance(upload, UploadFile) and upload.filename:
            content = await upload.read()
            media = {
                "filename": upload.filename,
                "content_type": upload.content_type or "application/octet-stream",
                "size_bytes": len(content),
            }
        return raw_filters, style_description, media

    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON request body must be an object")
        return payload.get("filters", {}), str(payload.get("style_description", "")).strip(), payload.get("media")

    raise HTTPException(status_code=400, detail="Content-Type must be application/json or multipart/form-data")


@router.post("/searches", status_code=201)
async def create_search(request: Request) -> dict[str, Any]:
    raw_filters, style_description, media = await _read_request_payload(request)

    if media is not None and not isinstance(media, dict):
        raise HTTPException(status_code=400, detail="media must be an object when supplied")
    if media and not str(media.get("content_type", "")).startswith(("image/", "video/")):
        raise HTTPException(status_code=400, detail="media.content_type must be an image or video MIME type")

    filters = _normalize_filters(raw_filters)
    ranked = recommend(style_description, filters)

    search_id = f"search_{uuid.uuid4().hex[:12]}"
    _SEARCHES[search_id] = {
        "filters": filters,
        "style_description": style_description,
        "ranked": ranked,
    }

    return {
        "search": {
            "id": search_id,
            "created_at": datetime.now(UTC).isoformat(),
            "filters": filters,
            "style_description": style_description,
            "media": media,
        },
        "results": {"search_id": search_id, **_paginate(ranked, page=1, per_page=12)},
    }


@router.get("/searches/{search_id}/products")
def get_search_products(search_id: str, page: int = 1, per_page: int = 12) -> dict[str, Any]:
    search = _SEARCHES.get(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="search not found; create a search first")

    page = max(1, page)
    per_page = min(24, max(1, per_page))
    return {"search_id": search_id, **_paginate(search["ranked"], page, per_page)}
