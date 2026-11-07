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
5. **Card response.** Product-grid results must continue to expose `id`, `name`, `price`, `currency`, `image_url`, `product_url`, `dimensions_cm`, `style_tags`, `match_score`, and `match_reason` unless Jay agrees to a coordinated frontend change.
6. **Tests with changes.** Each new or changed endpoint requires an API contract test and an update to this document, the relevant frontend client, and the owner handoff in `WORKFLOW.md`.

## First production contracts to agree

| Contract | Backend owner | Must agree with |
| --- | --- | --- |
| Product catalog fields and detail response | A — Diwas | B, D |
| Search filters, ranking response, and explanation | B — Tem | A, C, D |
| Room media input, 3D job status, preview/scene URL response | C — Isaac | B, D |
