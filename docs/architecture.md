# BuyByFit architecture

## Current MVP

The shipped frontend is intentionally self-contained. It loads a local fictional catalogue, accepts a free-form room brief (typed or dictated where the browser supports the Web Speech API), and stores the submitted brief plus sort preference in tab-scoped session storage. It does not currently make network requests to `backend/` or to retailers.

```text
Browser
  └─ Next.js frontend ──> local mock catalogue + session storage
```

This keeps the prototype reliable while product ingestion, AI search, and retailer verification are still being designed. The replacement point is the submit flow in `frontend/src/components/discover-view.tsx`.

## Intended request flow

```text
Frontend
  ├─ Product discovery ──> Product service ──> Relational DB
  ├─ Recommendations ────> Logic service ────> Vector DB + Relational DB
  └─ Room upload/preview ─> 3D service ──────> External 3D API
                                                    └─> Relational DB (job/status/URLs)
```

## Service boundaries

- **Product service**: ingests retailer/API/scraped product data; normalizes images, descriptions, dimensions, links, and product metadata.
- **Logic service**: applies fit and attribute filters, then ranks candidates using embeddings/similarity and product constraints.
- **3D service**: accepts room imagery or measurements, calls the external 3D API, exposes job status and safe preview/scene URLs, and associates suitable products. This service does not write 3D binaries to local storage.
- **Relational database**: source of truth for products, dimensions, user/room metadata, links, and job state.
- **Vector database**: stores embeddings for product/room style and semantic similarity retrieval.
- **External 3D API**: owns upload processing, generated models, and rendering. Its credentials are environment variables; Isaac will create the provider client inside `app/services/three_d/` once its API contract is agreed.

## Placeholder conventions

The three service folders are intentionally empty apart from `.gitkeep`, so each owner can create the files that suit their implementation. Agree API request/response fields in [the API contract](../backend/app/api/API_CONTRACT.md) first; use `app/db` only for shared database connection code. The API mock server is available for contract testing, but is not wired into the current frontend MVP.
