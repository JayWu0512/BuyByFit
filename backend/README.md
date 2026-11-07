# Backend

Lightweight backend skeleton. API contracts are documented before implementation; each service can use the database adapters in `app/db` directly. Isaac will place the external 3D API client in the `three_d` service when it is needed.

```text
frontend -> documented API -> service -> db adapter -> database
                                    └-> external 3D API
```

The external 3D API owns upload processing and generated model files; store only its job/status/URL metadata in the relational database.

Before editing an area, check [WORKFLOW.md](WORKFLOW.md). It identifies the responsible person, the precise trigger for updating each module, and the required handoff/tests.

## Recommendation service

The production recommendation route is `POST /api/v1/searches` in
[`app/api/v1/searches.py`](app/api/v1/searches.py). It embeds the room brief
with `BAAI/bge-small-en-v1.5`, retrieves the nearest candidates from pgvector,
then applies category, budget, and dimension limits. Its result cards preserve
the CSV product metadata: description, images, retailer URL, materials,
dimensions, captions, and optional 3D/AR URLs.

Load the local catalogue exports before starting the API:

```bash
python scripts/import_catalog.py --dry-run
python scripts/import_catalog.py
uvicorn app.main:app --reload
```

`RELATIONAL_DATABASE_URL` belongs in `backend/.env` (or the process
environment) and points to PostgreSQL with the pgvector extension available.
The importer is idempotent; the source CSV files in `infra/` are intentionally
ignored by Git. Recommendation shaping and filter order are covered by
`python -m unittest discover -s tests`.

`python -m app.api.mock_server` remains available as a contract-only fallback.
The endpoint field rules and examples are in
[app/api/API_CONTRACT.md](app/api/API_CONTRACT.md) and
[app/api/MOCK_API.md](app/api/MOCK_API.md).
