# BuyByFit mock API

app.api.mock_server is a dependency-free, in-memory implementation of the search contract. Use it for client and contract tests when PostgreSQL, pgvector, or the recommendation service are unavailable. It is not the production recommendation service and does not implement room visualization.

## Run it

    cd backend
    python -m app.api.mock_server

The server listens on http://127.0.0.1:8000, enables permissive development CORS, and resets its in-memory product/search state when it stops.

## Supported endpoints

| Method | Path | Behaviour |
| --- | --- | --- |
| POST | /api/v1/searches | Accepts JSON or multipart filters/brief/media metadata and returns the first result page. |
| GET | /api/v1/searches/{search_id}/products | Returns a page from a mock search. |
| GET | /api/v1/products/{product_id} | Returns a mock product detail. |
| GET | /api/v1/health | Reports mock-server health. |

The request filters, response envelope, product-card fields, units, and error shape are defined in [API_CONTRACT.md](API_CONTRACT.md). Keep implementation and contract synchronized.

## Intentional limitations

- Uses an eight-product in-memory fixture and deterministic text/tag overlap scoring; it is not semantic retrieval.
- Reads uploaded media only to report filename, MIME type, and byte size, then discards it.
- Has no database, durable search state, real retailer verification, or external 3D/AI provider calls.
- Exists for local integration/contract work only. The customer-facing Next.js app normally uses its own server route, configured FastAPI service, Supabase, or fictional fallback catalogue.
