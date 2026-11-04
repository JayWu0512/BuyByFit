# BuyByFit

A smart furniture shopping platform that helps users discover furniture matching their room's style and dimensions, with personalized recommendations, automatic room measurements, and realistic 3D previews.

## Project structure

```text
frontend/                         # Customer-facing application
  src/
    features/                      # product browsing, recommendations, room upload, 3D preview
    components/                    # shared UI components
    lib/                           # API client and shared utilities

backend/
  app/
    api/                           # mock server and API contract documentation
    services/
      product/                     # product ingestion, normalization, catalog search
      logic/                       # filters and recommendation/ranking logic
      three_d/                     # room analysis, scene creation, visualization contracts
    db/                            # relational and vector database adapters

docs/                              # architecture and integration decisions
infra/                             # deployment and local-infrastructure configuration
```

The backend is deliberately lightweight at this stage. Each service may call the database adapter it needs; API contracts live in [backend/app/api/API_CONTRACT.md](backend/app/api/API_CONTRACT.md). The 3D provider client will live within Isaac's `three_d` service when it is implemented. 3D assets and rendering are managed by the external API, so this repository does not keep a local `storage/` directory. See [the architecture note](docs/architecture.md) for the intended flow.

## Team ownership

| Owner | Scope | Primary directories | Deliverables |
| --- | --- | --- | --- |
| **A — Diwas** | Product data | `backend/app/services/product/` | Scraping/API ingestion, normalization, catalog fields, relational product records |
| **B — Tem** | Recommendation logic | `backend/app/services/logic/`, vector DB adapter | Dimension/style filters, embeddings, similarity search, ranking and recommendation explanations |
| **C — Isaac** | 3D integration | `backend/app/services/three_d/` | Room-input contract, external 3D API client, room attributes, scene/preview job status |
| **D — Jay** | Frontend | `frontend/` | Product discovery UI, recommendation results, room upload, 3D preview UI, API client integration |

## Collaboration rules

1. Keep implementation changes inside your owned directories. Discuss changes to `backend/app/api/API_CONTRACT.md`, `backend/app/db/`, or shared documentation with the affected owner before merging.
2. Define or update the request/response contract in `backend/app/api/API_CONTRACT.md` before connecting frontend and backend.
3. The request path is `frontend → API → service → database/external API`. Do not mix another owner's product, ranking, or 3D concerns into your service.
4. The 3D provider receives the room input through its API. Persist only the returned job ID, status, room attributes, and safe preview/scene URLs in the relational database—never API keys or generated binary assets.
5. Keep all credentials in `.env`; use `.env.example` only for non-secret variable names and sample values.

For the exact owner and update trigger of every backend area, read [the backend workflow](backend/WORKFLOW.md) before starting a task.

The initial API rules and the temporary frontend contract are in [backend/app/api/API_CONTRACT.md](backend/app/api/API_CONTRACT.md); the individual service folders intentionally start empty.
