# BuyByFit architecture

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

The three service folders are intentionally empty apart from `.gitkeep`, so each owner can create the files that suit their implementation. Agree API request/response fields in [the API contract](../backend/app/api/API_CONTRACT.md) first; use `app/db` only for shared database connection code.
