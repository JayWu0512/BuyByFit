"""Ranks products for a user's style/vibe query, then filters by fit.

Order matches docs/architecture.md: similarity-rank first (broad candidate
generation from the style text), then fit/attribute filters (dimensions,
category, price) narrow those candidates down to what actually works for the
user's space and budget.
"""

from __future__ import annotations

from typing import Any

from app.db.vector import similarity_search
from app.services.logic.embeddings import embed_query

CANDIDATE_POOL_SIZE = 50


def _matches_categories(product: dict[str, Any], categories: list[str]) -> bool:
    if not categories:
        return True
    product_type = (product.get("product_type") or "").lower()
    return product_type in categories


def _matches_colors(product: dict[str, Any], colors: list[str]) -> bool:
    if not colors:
        return True
    color = (product.get("color") or "").lower()
    return color in colors


def _within_price(product: dict[str, Any], min_price: float | None, max_price: float | None) -> bool:
    price = product.get("price")
    if price is None:
        # Most of the catalog (ABO dataset) has no price; don't exclude on absence.
        return True
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    return True


def _fits_dimensions(product: dict[str, Any], max_width_cm: float | None, max_depth_cm: float | None) -> bool:
    width = product.get("width_cm")
    depth = product.get("depth_cm")
    if max_width_cm is not None and width is not None and width > max_width_cm:
        return False
    if max_depth_cm is not None and depth is not None and depth > max_depth_cm:
        return False
    return True


def _passes_filters(product: dict[str, Any], filters: dict[str, Any]) -> bool:
    return (
        _matches_categories(product, filters.get("categories", []))
        and _matches_colors(product, filters.get("colors", []))
        and _within_price(product, filters.get("min_price"), filters.get("max_price"))
        and _fits_dimensions(product, filters.get("max_width_cm"), filters.get("max_depth_cm"))
    )


def _match_score(distance: float) -> int:
    similarity = max(0.0, 1.0 - distance)
    return min(99, round(similarity * 100))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _product_card(product: dict[str, Any]) -> dict[str, Any]:
    raw_image_urls = product.get("image_urls") or []
    image_urls = [str(url) for url in raw_image_urls if isinstance(url, str) and url.strip()] if isinstance(raw_image_urls, list) else []
    return {
        "id": product["id"],
        "name": product["title"],
        "brand": product.get("brand"),
        "category": (product.get("product_type") or "").lower() or None,
        "price": product.get("price"),
        "currency": product.get("currency"),
        "image_url": image_urls[0] if image_urls else None,
        "image_urls": image_urls,
        "product_url": product.get("url"),
        "description": product.get("description"),
        "material": product.get("material"),
        "color": product.get("color"),
        "caption": product.get("caption"),
        "model_3d_url": product.get("model_3d_url"),
        "ar_model_url": product.get("ar_model_url"),
        "dimensions_cm": {
            "width": product.get("width_cm"),
            "depth": product.get("depth_cm"),
            "height": product.get("height_cm"),
        },
        "style_tags": _string_list(product.get("vibe_tags")) or _string_list(product.get("style")),
        "match_score": _match_score(product["distance"]),
        "match_reason": "Matches your style and selected room constraints.",
    }


def recommend(style_description: str, filters: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    """Return product cards ranked by style similarity, narrowed to fit filters."""
    query_vector = embed_query(style_description)
    candidates = similarity_search(query_vector, limit=CANDIDATE_POOL_SIZE)
    filtered = [c for c in candidates if _passes_filters(c, filters)]
    return [_product_card(product) for product in filtered[:limit]]
