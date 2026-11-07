# BuyByFit mock API

This is a dependency-free local API for contract testing before the real database, recommendation engine, and 3D provider are available. The current Next.js MVP uses its own local fictional catalogue and does not call this server yet.

```bash
cd backend
python -m app.api.mock_server
```

The server starts at `http://127.0.0.1:8000` and enables development CORS for every origin. It uses an in-memory catalog of eight furniture products. Search IDs disappear when the server stops.

## Screen 1 — submit preferences and optional room media

`POST /api/v1/searches`

Send JSON while building the UI, or `multipart/form-data` when testing the upload control. The mock accepts image/video media metadata but deliberately does **not** save the file.

```json
{
  "filters": {
    "categories": ["sofa", "chair", "table"],
    "colors": ["beige", "oak"],
    "min_price": 200,
    "max_price": 1500,
    "max_width_cm": 220,
    "max_depth_cm": 100
  },
  "style_description": "Warm Scandinavian living room with natural oak and soft neutral colors.",
  "media": {
    "filename": "living-room.jpg",
    "content_type": "image/jpeg",
    "size_bytes": 245000
  }
}
```

The response is `201 Created` and contains a `search.id` plus the first product grid page in `results`. Navigate to page 2 using the search ID. `media` is optional and must use an `image/*` or `video/*` MIME type when supplied.

For real browser file selection, submit a form with these fields:

```text
filters             JSON string matching the filters object above
style_description   free text
media               optional image or video file
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/searches \
  -F 'filters={"categories":["sofa","chair"],"max_width_cm":220}' \
  -F 'style_description=Warm Scandinavian room with oak furniture' \
  -F 'media=@./room.jpg;type=image/jpeg'
```

## Screen 2 — product-card grid

`GET /api/v1/searches/{search_id}/products?page=1&per_page=12`

Each `products` entry contains exactly what a shopping-card UI needs:

```json
{
  "id": "oak-haven-sofa",
  "name": "Oak Haven 3-Seat Sofa",
  "brand": "Northline Home",
  "category": "sofa",
  "price": 1290,
  "currency": "USD",
  "image_url": "https://images.unsplash.com/…",
  "product_url": "https://example.com/products/oak-haven-sofa",
  "dimensions_cm": { "width": 198, "depth": 92, "height": 82 },
  "style_tags": ["scandinavian", "minimal"],
  "match_score": 87,
  "match_reason": "Matches your style and selected room constraints."
}
```

`GET /api/v1/products/{product_id}` returns a full item for a future product-detail page. `GET /api/v1/health` confirms that the mock is running.

## Current mock behavior

- Filters categories, colors, price, maximum width, and maximum depth.
- Uses deterministic overlap between style text/tags to create a `match_score`; it is not an ML recommendation system.
- Accepts request bodies up to 25 MB, reads uploaded media only to report filename/type/size, then discards it.
- Does not call the external 3D API. Isaac will replace this hand-off with the actual room/3D job APIs while retaining the documented room media contract.

When a real contract replaces an endpoint, update this document, `API_CONTRACT.md`, the endpoint's tests, and Jay's frontend client in the same coordinated change.
