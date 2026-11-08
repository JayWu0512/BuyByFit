# BuyByFit API contract

This document is the source of truth for the FastAPI HTTP API consumed through Next.js same-origin proxy routes. Update it, the frontend mapping, and tests together whenever a browser-visible field changes.

## Conventions

- Base path: /api/v1
- Content type: JSON unless an endpoint explicitly uses multipart form data.
- Error body: an object with error.message and error.status.
- Dimensions: centimetres. Unknown source dimensions are null and must never be represented as zero.
- Prices: price is a source price when known. price_estimate is a separate optional range and is never a verified price.
- Product URLs: product_url is an outbound source/retailer URL and must be safe to open in a new tab.

## Search

### POST /searches

Creates an in-memory search and returns its first product page. The service accepts JSON or multipart form data; Next.js currently sends JSON.

Example JSON request:

    {
      "filters": {
        "categories": ["sofa", "chair"],
        "colors": ["oak", "beige"],
        "min_price": 200,
        "max_price": 1500,
        "max_width_cm": 220,
        "max_depth_cm": 100
      },
      "style_description": "A calm, light-filled living room with oak and linen."
    }

style_description is required. Every filter is optional. Multipart clients send filters as a JSON text field, style_description as text, and may attach a media image/video field for future search workflows.

Success status: 201 Created. The response has a search object (id, created_at, filters, style_description) and results (search_id, products, pagination).

### GET /searches/{search_id}/products?page=1&per_page=12

Returns a page from a search created by this running process. per_page is clamped to 1–24. Search state is not durable across a service restart.

## Product-card shape

Every result card preserves this stable field set:

| Field | Meaning |
| --- | --- |
| id, name | Stable source identifier and product title. |
| brand, category | Optional source brand and normalized product type. |
| price, currency | Verified/collected source price and its currency, when known. |
| price_estimate | Optional low/high/basis range only when price is unavailable. |
| image_url, image_urls | Primary and alternate source image URLs. |
| product_url | Outbound retailer/source listing. |
| description, material, color, caption | Optional source/enriched display information. |
| model_3d_url, ar_model_url | Optional GLB/AR asset URLs. |
| dimensions_cm | Object with width, depth, and height in centimetres. |
| style_tags | Array of descriptive style/vibe tags. |
| match_score, match_reason | Ranking output and a visitor-readable explanation. |

Fields without source data may be null; style_tags is always an array. The canonical example is maintained by the response mapper in frontend/src/lib/api.ts.

## Room visualization

The browser reaches these endpoints through Next.js. FastAPI owns validation, private storage, job state, and provider calls.

| Endpoint | Request | Response |
| --- | --- | --- |
| POST /rooms | Multipart photo (JPEG/PNG, 1 byte–15 MB); optional pitch_deg (-60–89), room_width_cm and room_depth_cm (100–2000) | 201 with room_id, scene, and photo_url |
| POST /rooms/{room_id}/visualizations | JSON brief plus 1–30 product candidates | 202 with job_id |
| GET /visualizations/{job_id} | None | Job status, stage, elapsed time, and a result or error. |
| POST /rooms/{room_id}/visualizations/{job_id}/feedback | good/bad verdict, optional issue IDs and note | 201 with ok true |
| GET /rooms/{room_id}/files/{name} | None | Stored JPEG/PNG input, guide, or render. JSON files are never served. |

Each visualization product supplies id, name, optional category, required width_cm/depth_cm/height_cm, and optional image_url/product_url. The room service selects from those candidates; it does not independently crawl retailer sites.

Valid feedback issue IDs: removed_existing, missing_piece, floating, wrong_size, wrong_product, wrong_orientation, blocks_path, room_changed, artifacts, off_brief, and unrealistic.

## Health

GET /health returns status ok and mode live when the FastAPI process is available.
