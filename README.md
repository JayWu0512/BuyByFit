# BuyByFit

BuyByFit helps people discover furniture for the room they actually have. The current deliverable is a polished, Scandinavian-inspired frontend MVP: visitors describe a room naturally, optionally dictate a brief, and then browse a fictional catalogue with clear dimensions and materials.

## Current status

- `frontend/` is a working Next.js 15 application with local mock data and fictional product photography.
- A free-form room brief is the primary discovery flow; all non-empty briefs intentionally return the same 16 mock products until AI search is connected.
- Search copy and sort state persist within the browser tab when a visitor opens a product and returns to results.
- Product details deliberately disable purchasing because retailer URLs are not yet verified.
- `backend/` documents the planned API and provides a separate temporary mock server, but the frontend does not currently call it.

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Before sharing a change, run:

```bash
cd frontend
npm run typecheck
npm run build
```

For routes, project layout, browser support, mock-data boundaries, and integration notes, see [frontend/README.md](frontend/README.md).

## Repository layout

```text
frontend/     Customer-facing Next.js MVP and static demonstration assets
backend/      API contract, temporary mock server, and future service boundaries
docs/         Architecture and integration decisions
infra/        Deployment and local-infrastructure notes
```

## Planned architecture

```text
BuyByFit frontend
  └─ Search/recommendation API
       ├─ Product catalogue service ──> relational database
       ├─ Recommendation service ─────> vector + relational databases
       └─ Optional room/3D service ───> external 3D provider
```

The frontend must use an agreed API contract before production services are connected. See [the API contract](backend/app/api/API_CONTRACT.md), [the mock API guide](backend/app/api/MOCK_API.md), and [the architecture note](docs/architecture.md).

## Collaboration and safety

- Keep frontend implementation inside `frontend/`; coordinate changes to API contracts and shared documentation with the relevant owners.
- Never commit `.env` files, API keys, database volumes, generated assets, `node_modules`, or Next.js build output.
- All current products, prices, retailers, and imagery are fictional demonstration content. Do not publish them as real inventory.
- The detailed ownership and handoff rules are in [backend/WORKFLOW.md](backend/WORKFLOW.md).
