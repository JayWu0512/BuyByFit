# Infrastructure

No infrastructure stack is required for the current self-contained frontend MVP. Run the web app locally from `frontend/` with `npm run dev`.

When the production search, catalogue, and room services are selected, add the chosen local-development and deployment configuration here (for example Compose, Terraform, or Kubernetes). The design must account for:

- a relational database for products, room metadata, and job status;
- a vector database for semantic recommendation retrieval;
- a queue or job mechanism if room/3D processing is asynchronous;
- the external 3D provider, which retains uploaded and generated binary assets.

Keep secrets, persistent database volumes, generated 3D assets, and provider credentials out of Git. The intended service boundaries are described in [the architecture note](../docs/architecture.md).

## Local catalogue exports

`products_rows.csv` and `product_embeddings_rows.csv` are local ingestion exports and intentionally remain outside Git. They contain the product title, retailer URL, images, dimensions, materials, descriptions, and precomputed `BAAI/bge-small-en-v1.5` vectors used by the recommendation service.

To load a matching pair of exports into the configured PostgreSQL database with pgvector:

```bash
cd backend
python scripts/import_catalog.py --dry-run
python scripts/import_catalog.py
```

The importer creates the `products` and `product_embeddings` tables when needed and upserts records, so it is safe to rerun when a newer CSV export arrives. It reads the database connection only from `backend/.env` or the process environment; never commit that file.
