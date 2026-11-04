"""Dependency-free mock API for the BuyByFit frontend.

Run from this directory:
    python -m app.api.mock_server

The server intentionally keeps search state in memory and never stores uploaded
media. It is for UI integration only; replace it with the real API/provider
adapters when those are ready.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


HOST = "127.0.0.1"
PORT = 8000
MAX_REQUEST_BYTES = 25 * 1024 * 1024
SEARCHES: dict[str, dict[str, Any]] = {}


# These fixtures stand in for the future relational product catalog. Images are
# remote placeholders so a frontend can render a realistic product-card grid.
PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "oak-haven-sofa",
        "name": "Oak Haven 3-Seat Sofa",
        "brand": "Northline Home",
        "category": "sofa",
        "price": 1290,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/oak-haven-sofa",
        "dimensions_cm": {"width": 198, "depth": 92, "height": 82},
        "colors": ["beige", "oak"],
        "style_tags": ["scandinavian", "minimal", "warm", "natural"],
        "description": "A warm neutral sofa with an oak base and generous everyday seating.",
    },
    {
        "id": "cloud-boucle-chair",
        "name": "Cloud Bouclé Lounge Chair",
        "brand": "Atelier Forma",
        "category": "chair",
        "price": 720,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1592078615290-033ee584e267?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/cloud-boucle-chair",
        "dimensions_cm": {"width": 78, "depth": 82, "height": 74},
        "colors": ["cream"],
        "style_tags": ["minimal", "soft", "modern", "cozy"],
        "description": "A compact textured lounge chair for calm, light-filled rooms.",
    },
    {
        "id": "linea-walnut-table",
        "name": "Linea Walnut Dining Table",
        "brand": "Morrow",
        "category": "table",
        "price": 980,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1617806118233-18e1de247200?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/linea-walnut-table",
        "dimensions_cm": {"width": 180, "depth": 90, "height": 75},
        "colors": ["walnut", "brown"],
        "style_tags": ["mid-century", "warm", "modern", "wood"],
        "description": "A clean-lined walnut table that anchors a modern dining room.",
    },
    {
        "id": "harbor-storage-console",
        "name": "Harbor Low Storage Console",
        "brand": "Northline Home",
        "category": "storage",
        "price": 840,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1616486338812-3dadae4b4ace?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/harbor-storage-console",
        "dimensions_cm": {"width": 160, "depth": 42, "height": 62},
        "colors": ["oak", "beige"],
        "style_tags": ["scandinavian", "minimal", "storage", "natural"],
        "description": "Low-profile oak storage with softly rounded pull details.",
    },
    {
        "id": "terra-sectional",
        "name": "Terra Modular Sectional",
        "brand": "Studio Common",
        "category": "sofa",
        "price": 2180,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1550254478-ead40cc54513?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/terra-sectional",
        "dimensions_cm": {"width": 278, "depth": 170, "height": 78},
        "colors": ["rust", "terracotta"],
        "style_tags": ["eclectic", "warm", "contemporary", "statement"],
        "description": "A generous modular sectional in a warm terracotta performance fabric.",
    },
    {
        "id": "arc-floor-lamp",
        "name": "Arc Linen Floor Lamp",
        "brand": "Sora Living",
        "category": "lighting",
        "price": 310,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/arc-floor-lamp",
        "dimensions_cm": {"width": 42, "depth": 42, "height": 158},
        "colors": ["cream", "black"],
        "style_tags": ["minimal", "modern", "ambient", "cozy"],
        "description": "A paper-linen shade brings diffuse ambient light to a reading corner.",
    },
    {
        "id": "cove-coffee-table",
        "name": "Cove Travertine Coffee Table",
        "brand": "Atelier Forma",
        "category": "table",
        "price": 650,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1533090481720-856c6e3c1fdc?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/cove-coffee-table",
        "dimensions_cm": {"width": 110, "depth": 65, "height": 35},
        "colors": ["cream", "stone"],
        "style_tags": ["organic", "minimal", "modern", "luxury"],
        "description": "A rounded, low coffee table with a softly veined stone finish.",
    },
    {
        "id": "mono-desk",
        "name": "Mono Compact Work Desk",
        "brand": "Grid Works",
        "category": "desk",
        "price": 460,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1518455027359-f3f8164ba6bd?auto=format&fit=crop&w=900&q=80",
        "product_url": "https://example.com/products/mono-desk",
        "dimensions_cm": {"width": 120, "depth": 60, "height": 74},
        "colors": ["white", "oak"],
        "style_tags": ["minimal", "small-space", "scandinavian", "functional"],
        "description": "A slim work desk designed for bright apartments and compact rooms.",
    },
]


def utc_now() -> str:
    """Return an ISO timestamp suitable for mock responses."""
    return datetime.now(UTC).isoformat()


def product_card(product: dict[str, Any], score: int) -> dict[str, Any]:
    """Return the compact object used by the second-page product grid."""
    return {
        "id": product["id"],
        "name": product["name"],
        "brand": product["brand"],
        "category": product["category"],
        "price": product["price"],
        "currency": product["currency"],
        "image_url": product["image_url"],
        "product_url": product["product_url"],
        "dimensions_cm": product["dimensions_cm"],
        "style_tags": product["style_tags"],
        "match_score": min(score, 99),
        "match_reason": "Matches your style and selected room constraints.",
    }


def tokens(value: Any) -> set[str]:
    """Normalize a small free-text input into comparison tokens."""
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return set(re.findall(r"[a-z0-9-]+", str(value).lower()))


def coerce_number(value: Any, field: str) -> float | None:
    """Return an optional numeric filter or report a client error."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a number") from error


def normalize_filters(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the first-page filter inputs into a predictable mock shape."""
    raw = payload.get("filters", {})
    if not isinstance(raw, dict):
        raise ValueError("filters must be an object")

    categories = raw.get("categories", [])
    colors = raw.get("colors", [])
    if isinstance(categories, str):
        categories = [categories]
    if isinstance(colors, str):
        colors = [colors]
    if not isinstance(categories, list) or not isinstance(colors, list):
        raise ValueError("categories and colors must be arrays")

    return {
        "categories": [str(item).lower() for item in categories],
        "colors": [str(item).lower() for item in colors],
        "min_price": coerce_number(raw.get("min_price"), "filters.min_price"),
        "max_price": coerce_number(raw.get("max_price"), "filters.max_price"),
        "max_width_cm": coerce_number(raw.get("max_width_cm"), "filters.max_width_cm"),
        "max_depth_cm": coerce_number(raw.get("max_depth_cm"), "filters.max_depth_cm"),
    }


def score_products(filters: dict[str, Any], style_description: str) -> list[dict[str, Any]]:
    """Filter mock catalog and rank it with deterministic tag-overlap scoring."""
    query_tokens = tokens(style_description) | tokens(filters["colors"])
    matches: list[dict[str, Any]] = []

    for product in PRODUCTS:
        dimensions = product["dimensions_cm"]
        if filters["categories"] and product["category"] not in filters["categories"]:
            continue
        if filters["min_price"] is not None and product["price"] < filters["min_price"]:
            continue
        if filters["max_price"] is not None and product["price"] > filters["max_price"]:
            continue
        if filters["max_width_cm"] is not None and dimensions["width"] > filters["max_width_cm"]:
            continue
        if filters["max_depth_cm"] is not None and dimensions["depth"] > filters["max_depth_cm"]:
            continue

        product_tokens = tokens(product["style_tags"]) | tokens(product["colors"]) | tokens(product["name"])
        tag_matches = len(query_tokens & product_tokens)
        score = 55 + tag_matches * 12
        if set(filters["colors"]) & set(product["colors"]):
            score += 8
        matches.append({"product": product, "score": score})

    return sorted(matches, key=lambda match: (-match["score"], match["product"]["price"]))


def page_of(search: dict[str, Any], page: int, per_page: int) -> dict[str, Any]:
    """Paginate a stored mock search."""
    ranked = search["ranked"]
    total = len(ranked)
    start = (page - 1) * per_page
    return {
        "search_id": search["id"],
        "products": [product_card(item["product"], item["score"]) for item in ranked[start : start + per_page]],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    }


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Parse the few multipart fields required by this mock without persisting files."""
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if not boundary_match:
        raise ValueError("multipart/form-data requires a boundary")
    boundary = boundary_match.group(1).strip('"').encode()
    fields: dict[str, Any] = {}
    media: dict[str, Any] | None = None

    for chunk in body.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--" or b"\r\n\r\n" not in chunk:
            continue
        header_bytes, value = chunk.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("utf-8", errors="replace")
        value = value.rstrip(b"\r\n")
        disposition = re.search(r'Content-Disposition:.*?name="([^"]+)"', headers, re.IGNORECASE)
        if not disposition:
            continue
        name = disposition.group(1)
        filename = re.search(r'filename="([^"]*)"', headers, re.IGNORECASE)
        if filename:
            content_type_match = re.search(r"Content-Type:\s*([^\r\n]+)", headers, re.IGNORECASE)
            media = {
                "filename": filename.group(1) or "upload",
                "content_type": content_type_match.group(1).strip() if content_type_match else "application/octet-stream",
                "size_bytes": len(value),
                "stored": False,
            }
        else:
            fields[name] = value.decode("utf-8", errors="replace")
    return fields, media


class MockApiHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing the documented mock endpoints."""

    server_version = "BuyByFitMockAPI/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        """Keep development logging compact."""
        print(f"[mock-api] {self.address_string()} - {format % args}")

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json(status, {"error": {"message": message, "status": status.value}})

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler convention
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def request_payload(self) -> dict[str, Any]:
        """Read either JSON or multipart form data without retaining media bytes."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Content-Length must be an integer") from error
        if content_length <= 0:
            raise ValueError("request body is required")
        if content_length > MAX_REQUEST_BYTES:
            raise ValueError("request body exceeds the 25 MB mock limit")

        body = self.rfile.read(content_length)
        content_type = self.headers.get("Content-Type", "application/json")
        if content_type.startswith("application/json"):
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError("request body must be valid JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("JSON request body must be an object")
            return payload
        if content_type.startswith("multipart/form-data"):
            fields, media = parse_multipart(body, content_type)
            try:
                filters = json.loads(fields.get("filters", "{}"))
            except json.JSONDecodeError as error:
                raise ValueError("multipart filters field must contain valid JSON") from error
            return {
                "filters": filters,
                "style_description": fields.get("style_description", ""),
                "media": media,
            }
        raise ValueError("Content-Type must be application/json or multipart/form-data")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler convention
        if urlsplit(self.path).path != "/api/v1/searches":
            self.send_error_json(HTTPStatus.NOT_FOUND, "endpoint not found")
            return
        try:
            payload = self.request_payload()
            filters = normalize_filters(payload)
            style_description = str(payload.get("style_description", "")).strip()
            media = payload.get("media")
            if media is not None and not isinstance(media, dict):
                raise ValueError("media must be an object when supplied")
            if media and not str(media.get("content_type", "")).startswith(("image/", "video/")):
                raise ValueError("media.content_type must be an image or video MIME type")

            search_id = f"search_{uuid.uuid4().hex[:12]}"
            search = {
                "id": search_id,
                "created_at": utc_now(),
                "filters": filters,
                "style_description": style_description,
                "media": media,
                "ranked": score_products(filters, style_description),
            }
            SEARCHES[search_id] = search
            response = {
                "search": {
                    "id": search_id,
                    "created_at": search["created_at"],
                    "filters": filters,
                    "style_description": style_description,
                    "media": media,
                },
                "results": page_of(search, page=1, per_page=12),
            }
            self.send_json(HTTPStatus.CREATED, response)
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler convention
        parsed = urlsplit(self.path)
        if parsed.path == "/api/v1/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "mode": "mock", "product_count": len(PRODUCTS)})
            return

        product_match = re.fullmatch(r"/api/v1/products/([a-z0-9-]+)", parsed.path)
        if product_match:
            product = next((item for item in PRODUCTS if item["id"] == product_match.group(1)), None)
            if product is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, "product not found")
            else:
                self.send_json(HTTPStatus.OK, {"product": product})
            return

        search_match = re.fullmatch(r"/api/v1/searches/(search_[a-f0-9]+)/products", parsed.path)
        if search_match:
            search = SEARCHES.get(search_match.group(1))
            if search is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, "search not found; create a search first")
                return
            query = parse_qs(parsed.query)
            try:
                page = max(1, int(query.get("page", ["1"])[0]))
                per_page = min(24, max(1, int(query.get("per_page", ["12"])[0])))
            except ValueError:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "page and per_page must be integers")
                return
            self.send_json(HTTPStatus.OK, page_of(search, page, per_page))
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "endpoint not found")


def main() -> None:
    """Start the local mock API server."""
    server = ThreadingHTTPServer((HOST, PORT), MockApiHandler)
    print(f"BuyByFit mock API listening on http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping mock API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
