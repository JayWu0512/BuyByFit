# Backend workflow and ownership

This is the source of truth for collaboration. Check it before creating or changing a backend file. A person may make a small cross-area fix, but the listed primary owner must review a change that alters a contract or behavior.

## Working sequence

Use this order when a feature crosses teams:

1. The backend owner proposes the contract in `app/api/API_CONTRACT.md` before creating implementation files in their service directory.
2. The affected owners agree on field names, required/optional fields, error states, and the example response.
3. The backend owner implements their service and database/API calls, then creates the production route only when the chosen framework requires it; add tests in the same pull request.
4. Jay wires the documented API contract into `frontend/`; a contract change after that requires updating both backend tests and the frontend API client in the same coordinated change.

Never put product scraping, recommendation math, or 3D-provider calls in a route handler. Do not commit `.env`, API keys, database dumps, uploads, or generated 3D assets.

## Directory and file map

| Path | Primary owner | Update it when | What belongs here / required coordination |
| --- | --- | --- | --- |
| `app/main.py` | Shared: A, B, C | The team selects the web framework, registers a new route group, or changes application startup | App construction and route registration only. All affected backend owners review. Do this after the first endpoint contracts are agreed. |
| `app/__init__.py` | Shared | Package-wide initialization is genuinely needed | Usually do not edit it. No product, logic, or 3D implementation belongs here. |
| `app/api/` | Endpoint owner: A products, B recommendations, C rooms | A production endpoint has an agreed contract in `app/api/API_CONTRACT.md` | Contains the temporary mock server and all API documentation. Create production route files only at that point. Routes validate/translate HTTP only; they do not contain scraping, ranking, or 3D-provider calls. Jay reviews frontend-consumed responses. |
| `app/core/config.py` | Shared; proposer owns review | A new non-secret configuration variable is needed | Add validated configuration and update both `.env.example` files. The person adding the dependency documents why; never add actual secrets. |
| `app/core/__init__.py` | Shared | Shared cross-cutting package code is needed | Usually do not edit. Logging/auth/error handling will be added here only after the team agrees on a common approach. |
| `app/db/relational.py` | A — Diwas for product data; C — Isaac for room/job data | A or C needs a new persisted entity/query | Keep connection/provider mechanics here; service-specific queries stay in the owning service. C gets A review before altering shared relational configuration or migrations. |
| `app/db/vector.py` | B — Tem | B chooses the vector DB, embedding collection, or similarity query | Store/retrieve vectors only. Product metadata remains in relational DB; coordinate embedding identifiers with A and room-style vectors with C. |
| `app/db/__init__.py` | Shared | Package initialization is required by the chosen DB library | Normally no edit. It must not hold business queries or credentials. |
| `app/services/product/` | A — Diwas | After the product endpoint/input/output contract is agreed | Intentionally empty. Diwas chooses files for ingestion, normalization, and catalog behavior. Notify B of ranking fields and D of UI fields. |
| `app/services/logic/` | B — Tem | After the search/recommendation contract and required product/room fields are agreed | Intentionally empty. Tem chooses files for filters, embeddings, and ranking. Agree units with A and room inputs with C before implementation. |
| `app/services/three_d/` | C — Isaac | After room-media and 3D-job contracts are agreed | Intentionally empty. Isaac chooses files for room analysis, provider job orchestration, and preview handling. No local generated assets. |
| `app/services/` | Shared | The selected framework requires package wiring | Keep empty until package wiring is actually required; never place cross-service implementation here. |
| `backend/tests/` | Every owner | Any behavior is added or changed | Add/update unit tests in the same PR: A product/normalization, B filters/ranking, C provider-status mapping, D frontend tests in `frontend/`. Add API contract tests for changed endpoints. |
| `backend/.env.example` and root `.env.example` | Person adding a config variable | A new environment variable is introduced | Add non-secret name and safe example only; update `app/core/config.py` in the same change. |
| `app/api/mock_server.py` | Shared temporary integration tool | The mock request/response contract changes before production APIs replace it | Keep it dependency-free and in-memory. Update `app/api/MOCK_API.md` and `app/api/API_CONTRACT.md`, and have A/B/C review changes to their response fields; D verifies the frontend flow. Do not add production business logic here. |
| `app/api/MOCK_API.md`, `app/api/API_CONTRACT.md` | Shared API documentation | A mock/production endpoint, field, error, or frontend flow changes | Keep request/response examples synchronized with `mock_server.py`; agree contracts here before service implementation begins. |
| `backend/logs/` | Nobody | Never manually commit/update | Runtime-only local logs. Git keeps only `.gitkeep`. |
| `backend/README.md`, `backend/WORKFLOW.md` | Shared; change proposer | Architecture, ownership, a boundary, or workflow changes | Update documentation in the same PR as the relevant change; notify every affected owner. |

## Required handoffs

### A — Diwas: product data

Before A starts an endpoint, agree the Product request/response in `app/api/API_CONTRACT.md`. After product dimensions, descriptions, image URLs, and attributes are stable, notify B (ranking inputs) and D (catalog UI fields). A is free to choose the product-service files and must add tests whenever a source mapping changes.

### B — Tem: logic and recommendations

Start after A has provided the product fields/units and C has described any room attributes needed for fit. Agree the filter/recommendation API contract before creating any logic files. When ranking output changes, notify D because explanation/score/filter UI may change.

### C — Isaac: 3D integration

Start by agreeing the room-upload and job-status API contract with D. Add the 3D provider client only after the provider's request/response behavior is known. Once room attributes are stable, notify B; once status and preview URL formats are stable, notify D. Generated files remain with the provider.

### D — Jay: frontend

Do not depend on endpoint implementation details or call an external 3D provider directly. Start each feature once the corresponding API contract has an example request/response. Raise a contract change request before UI needs a new field; update frontend handling when A, B, or C changes a shared response.

## Pull request checklist

- [ ] My change stays within the assigned boundary, or the primary owner reviewed it.
- [ ] I updated `app/api/API_CONTRACT.md` before changing a shared contract.
- [ ] I added/updated tests in the same PR.
- [ ] I updated `.env.example` and `core/config.py` together, if configuration changed.
- [ ] I notified each affected owner and updated this document if ownership or the flow changed.
