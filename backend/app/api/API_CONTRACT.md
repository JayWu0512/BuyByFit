# API contract rules

This document is the only required starting point for backend API work. Create service or production-route files only when their contract is agreed by the owning backend member and Jay.

## Temporary API contract: mock server

`mock_server.py` provides an agreed integration target while production services are designed. The current Next.js frontend is self-contained and does **not** call these endpoints yet; when it does, the implementation and this document must be updated together.

| Endpoint | Owner when production replaces it | Purpose |
| --- | --- | --- |
| `POST /api/v1/searches` | A + B + C | Receive first-page filters, style description, and optional room image/video metadata; return a search and first product grid page. |
| `GET /api/v1/searches/{search_id}/products` | B | Return paginated, ranked product cards. |
| `GET /api/v1/products/{product_id}` | A | Return product detail. |
| `GET /api/v1/health` | Shared | Development health check. |

Exact request/response examples are in [MOCK_API.md](MOCK_API.md). The mock is temporary: it provides a stable interface for the frontend, not a prescribed production implementation.

## Rules for creating a production endpoint

1. **Contract first.** Before creating a route or service file, add the request/response definition and example payload to this document (or the future OpenAPI document). Name the owning team member.
2. **Shared fields require agreement.** A, B, and C own their domains; Jay reviews every request or response consumed by the frontend before merge.
3. **Version and errors.** Keep public endpoints under `/api/v1`. Return JSON errors as `{"error": {"message": "…", "status": 400}}`. Do not silently change or remove a frontend field.
4. **Media handling.** The input form accepts an optional image/video. The production 3D provider owns uploaded binaries; persist only approved metadata, job status, and safe result URLs. Never return credentials.
5. **Card response.** Product-grid results must continue to expose `id`, `name`, `price`, `currency`, `image_url`, `image_urls`, `product_url`, `description`, `material`, `color`, `caption`, `model_3d_url`, `ar_model_url`, `dimensions_cm`, `style_tags`, `match_score`, and `match_reason` unless Jay agrees to a coordinated frontend change. `product_url` is the real retailer destination and must be safe to open in a new tab.
6. **Tests with changes.** Each new or changed endpoint requires an API contract test and an update to this document, the relevant frontend client, and the owner handoff in `WORKFLOW.md`.

## First production contracts to agree

| Contract | Backend owner | Must agree with |
| --- | --- | --- |
| Product catalog fields and detail response | A — Diwas | B, D |
| Search filters, ranking response, and explanation | B — Tem | A, C, D |
| Room media input, 3D job status, preview/scene URL response | C — Isaac | B, D |

## Room visualization (C — Isaac) — proposed, needs B + D sign-off

"See these pieces in your room" on Discover: the user's room photo + the brief + the search results already on
screen -> the room restyled with some of those products, placed at their real size. Implemented in
`app/api/v1/rooms.py` + `app/services/three_d/`; the frontend calls same-origin Next.js routes with the same paths,
which forward to this service (`ROOM_API_URL`, else `RECOMMENDATION_API_URL`).

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /api/v1/rooms` | multipart: `photo` (JPEG/PNG, <= 15 MB), optional `pitch_deg` (phone tilt, -60..89, from the in-page camera) | `201 {room_id, scene, photo_url}` |
| `POST /api/v1/rooms/{room_id}/visualizations` | `{brief, products: [{id, name, category, width_cm, depth_cm, height_cm, image_url, product_url}]}` (1–30 search results) | `202 {job_id}` |
| `GET /api/v1/visualizations/{job_id}` | — | `{status: queued\|running\|done\|error, stage: design\|place\|render\|verify\|done, elapsed_s, info: {guide_url?}, result?, error?}` |
| `GET /api/v1/rooms/{room_id}/files/{name}` | — | the room photo, placement guide or render (image) |

`result`: `{vibe, photo_url, render_url, items: [{role, product: {id, name, category, image_url, product_url, size_cm}, placed_at_true_size, alternatives: [...]}], styling: [str], timings_s}`.
A run takes ~30–60 s (Gemini on Vertex: design, true-size placement, image render, size check, one retry), so it
is a background job polled every ~2.5 s. Errors use the usual `{"error": {"message", "status"}}` shape.
