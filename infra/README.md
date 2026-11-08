# Infrastructure and catalogue imports

`infra/` documents the local inputs and deployment concerns for BuyByFit's live catalogue paths. The Next.js application itself does not require infrastructure to run: without external configuration it uses its bundled fictional catalogue.

## Catalogue exports

Local CSV exports such as `products_rows.csv` and `product_embeddings_rows.csv` are ingestion inputs. They are intentionally excluded from Git because they can contain retailer source data, images, descriptions, and embeddings that are refreshed outside this repository.

The current importer expects a paired product/embedding export and upserts into PostgreSQL with pgvector:

```bash
cd backend
python scripts/import_catalog.py --dry-run
python scripts/import_catalog.py
```

The importer creates/updates `products` and `product_embeddings` as needed and is intended to be idempotent for a matching CSV pair. Use a test database and inspect a dry run before replacing production catalogue data.

## Data quality expectations

- Preserve the source product URL, source identifier, image URLs, dimensions, material, description, currency, and collection time where available.
- Treat missing price as missing—not zero. When a calibrated estimate is present, retain its low/high range and basis separately from a verified source price.
- Remove or mark records only after an explicit, repeatable availability check. A request failure or bot challenge is not evidence that a product is discontinued.
- Reject/flag malformed dimensions and unknown units before indexing them for room-fit search.
- Retain applicable image/model licenses and retailer/source attribution in the import pipeline.

## Runtime topology

| Component | Production responsibility |
| --- | --- |
| Vercel / Next.js | Customer UI and same-origin proxy routes. |
| Supabase or PostgreSQL + pgvector | Product records and vector similarity search. |
| FastAPI | Recommendation endpoint and optional room visualization. |
| Private object storage | Room upload/render persistence for the FastAPI room service. |
| Cloudflare Worker (optional) | Controlled collection/normalization helper; not a public checkout or inventory API. |

Configure connection strings and credentials through local `.env` files or the deployment platform's secret manager. Do not commit database volumes, exports, service-account credentials, uploaded room photos, generated renders, or private keys.

## Operations

Before enabling a live catalogue, establish a documented refresh cadence, source-specific rate limits/terms, an availability policy, and observability for failed imports. The request-serving search path should read indexed data; it should not scrape retailer pages synchronously.

See [the architecture note](../docs/architecture.md), [backend setup](../backend/README.md), and the frontend [environment reference](../frontend/.env.example).
