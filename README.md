# BuyByFit

BuyByFit helps people discover furniture for the room they actually have. The current deliverable is a polished, Scandinavian-inspired frontend MVP: visitors describe a room naturally, optionally dictate a brief, and then browse a fictional catalogue with clear dimensions and materials.

## Current status

- `frontend/` is a working Next.js 15 application with an always-available local demo catalogue and a same-origin Vercel Serverless search endpoint.
- A free-form room brief is the primary discovery flow. With `RECOMMENDATION_API_URL` configured, that endpoint forwards to the FastAPI semantic search service, which retrieves from the imported pgvector catalogue.
- Search copy and sort state persist within the browser tab when a visitor opens a product and returns to results.
- Source product cards preserve images, descriptions, materials, dimensions, retailer URLs, and optional 3D/AR fields from the local CSV export; local demo products remain explicitly fictional.
- `backend/` contains the catalogue importer and FastAPI recommendation route, plus a separate temporary mock server for contract work.

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

## Vercel deployment

Vercel should import [`JayWu0512/buy-by-fit`](https://github.com/JayWu0512/buy-by-fit), not this collaboration repository. The GitHub Actions workflow at [`.github/workflows/sync-vercel-deploy-repo.yml`](.github/workflows/sync-vercel-deploy-repo.yml) mirrors this repository's `frontend/` directory to that deployment repository whenever `main` changes. This keeps the team workflow simple: contributors merge only into this repository, and Vercel deploys the mirrored result. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the frontend type-check/build and backend recommendation tests first on every pull request and main-branch update.

One repository secret is required in **JayWu0512/BuyByFit**:

1. Create a fine-grained GitHub personal access token that has **Contents: Read and write** access to **only** `JayWu0512/buy-by-fit`.
2. Add it as the Actions secret `DEPLOY_REPO_TOKEN` in the source repository.
3. Ensure `buy-by-fit` is a dedicated deployment mirror. Its `main` branch will be replaced by the contents of `frontend/` on each successful source-repository merge.
4. Import `buy-by-fit` into Vercel with **Root Directory** set to `./`, **Install Command** `npm ci`, and **Build Command** `npm run build`. Vercel detects Next.js automatically.

Without that secret, the mirror workflow finishes successfully with a visible **skipped** notice rather than failing CI. Configure the secret before expecting Vercel to receive new commits.

`frontend/package.json` declares Node.js `>=20.9.0`, and `package-lock.json` is committed, so Vercel uses a reproducible dependency graph. Select the **Next.js** framework preset in Vercel, leave Output Directory blank, and use Node.js 22 LTS. No `vercel.json` is needed for this standard Next.js deployment.

The deployed frontend's search endpoint is same-origin (`/api/v1/searches`) and works as a Vercel Serverless Function against the fictional MVP catalogue by default. For semantic results from the imported product catalogue, deploy the FastAPI service and configure server-only `RECOMMENDATION_API_URL` with its deployed origin; the route then proxies requests without changing frontend code. `localhost` only works on a developer machine and must never be used as the Production value.

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
