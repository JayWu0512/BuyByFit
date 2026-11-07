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

## Room visualization service (Isaac)

`app/api/v1/rooms.py` + `app/services/three_d/` power "See these pieces in your room" on Discover: a room photo,
the brief and the search results go in; the room comes back restyled with some of those products at their real
size. Contract: [API_CONTRACT.md](app/api/API_CONTRACT.md) -> Room visualization.

It calls Gemini on Vertex AI with Google Application Default Credentials:

```bash
gcloud auth application-default login     # once, locally; a service account on a server
# optional: GOOGLE_CLOUD_PROJECT=buybyfit  (else the credentials' quota project)
uvicorn app.main:app --reload --port 8000
```

Photos and renders are written to `backend/storage/rooms/` (gitignored) and, when `THREE_D_BUCKET` is set, also
to `gs://$THREE_D_BUCKET/rooms/<room_id>/`. Cloud Run's disk is wiped on restart, so **set it in production**:
otherwise old results 404. Files missing locally are read back from the bucket. Each run also saves
`trace_<job>.json` (inputs, design, placements, every attempt's checks, errors) and the result page's
"How does this look?" saves `feedback_<job>.json`: the data for the reviewer model. Neither is served over HTTP.
Models are set by `THREE_D_DESIGN_MODEL`, `THREE_D_FAST_MODEL` and
`THREE_D_IMAGE_MODEL` (defaults: gemini-3.1-pro-preview, gemini-3-flash-preview, gemini-3.1-flash-image).
A run takes ~30-60 s; Vertex's per-minute quota on a new project can add retries (429) on top.
