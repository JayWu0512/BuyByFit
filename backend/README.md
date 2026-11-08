# BuyByFit backend

The FastAPI service supplies two server-side capabilities:

- Recommendation search: embeds a room brief, retrieves catalogue candidates from PostgreSQL with pgvector, applies practical constraints, and returns the shared product-card contract.
- Room visualization: accepts a room photo, starts an asynchronous Vertex AI restyling job, exposes progress/results, and stores structured feedback. When configured, a Tinker fine-tuned interior expert briefs the design step and returns style-only notes on the final render.

In the standard deployment, browsers do not call this service directly. The Next.js frontend proxies it through same-origin routes using RECOMMENDATION_API_URL and/or ROOM_API_URL.

## Requirements

- Python 3.12
- PostgreSQL with the vector extension for recommendation search
- Google Cloud Application Default Credentials for room visualization
- Local CSV catalogue exports in infra/ when importing a catalogue

## Local setup

    cd backend
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt

Create backend/.env locally; it is ignored by Git:

    RELATIONAL_DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/buybyfit
    GOOGLE_CLOUD_PROJECT=your-project-id
    THREE_D_BUCKET=your-private-bucket

Start the service:

    uvicorn app.main:app --reload --port 8000

The health endpoint is GET http://127.0.0.1:8000/api/v1/health.

## Catalogue import and checks

The importer reads the local paired exports under infra/ by default:

    python scripts/import_catalog.py --dry-run
    python scripts/import_catalog.py

Use --products and --embeddings for an alternate matching pair. The importer validates its inputs, creates the required schema when needed, and upserts catalogue records. Validate new exports against a non-production database first.

    python -m compileall -q app scripts
    python -m unittest discover -s tests -p "test_*.py"

## API surface

| Endpoint | Purpose |
| --- | --- |
| POST /api/v1/searches | Create ranked results from a brief and optional filters. |
| GET /api/v1/searches/{search_id}/products | Retrieve a page from a process-local search. |
| POST /api/v1/rooms | Validate/store a JPEG or PNG room photo and return a room ID/scene estimate. |
| POST /api/v1/rooms/{room_id}/visualizations | Start an asynchronous restyling job. |
| GET /api/v1/visualizations/{job_id} | Read job progress or result. |
| POST /api/v1/rooms/{room_id}/visualizations/{job_id}/feedback | Store structured result feedback. |
| GET /api/v1/rooms/{room_id}/files/{name} | Return a room input, guide, or render image. |

The stable HTTP contract, validation rules, and response fields are defined in [app/api/API_CONTRACT.md](app/api/API_CONTRACT.md).

## Room visualization operations

Authenticate locally with Google Application Default Credentials:

    gcloud auth application-default login

Attach a least-privileged service account in a deployed environment. Important configuration:

| Variable | Purpose |
| --- | --- |
| GOOGLE_CLOUD_PROJECT or VERTEX_PROJECT | Vertex AI project. |
| THREE_D_BUCKET | Private Cloud Storage bucket for durable room files. Required for durable Cloud Run results. |
| THREE_D_STORAGE_DIR | Local-development storage override. |
| THREE_D_DESIGN_MODEL, THREE_D_FAST_MODEL, THREE_D_IMAGE_MODEL | Optional model overrides. |
| TASTE_REVIEWER_MODEL + TINKER_API_KEY | Optional Thinking Machines fine-tuned reviewer. Both are required to activate it. |

Without THREE_D_BUCKET, files are saved under backend/storage/rooms/. That is appropriate only for local development because ephemeral hosts lose files when restarted. Room images, traces, feedback, and renders are private operational data and must never be committed.

The fine-tuned reviewer is best-effort: when its configuration is absent or a review call fails, room restyling continues without reviewer notes. Its model identifier and API key belong in the GCP secret/configuration system, never in Git.

## Development boundaries

- Route handlers validate and translate HTTP only; recommendation, storage, and provider work belongs in services.
- Update the API contract, frontend mapping, and tests together when a shared field changes.
- Do not run retailer scraping in a request handler. Ingest, normalize, verify, and index catalogue data separately.
- Keep secrets, uploads, renders, database data, and model caches out of Git.
