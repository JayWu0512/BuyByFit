# Backend

Lightweight backend skeleton. API contracts are documented before implementation; each service can use the database adapters in `app/db` directly. Isaac will place the external 3D API client in the `three_d` service when it is needed.

```text
frontend -> documented API -> service -> db adapter -> database
                                    └-> external 3D API
```

The external 3D API owns upload processing and generated model files; store only its job/status/URL metadata in the relational database.

Before editing an area, check [WORKFLOW.md](WORKFLOW.md). It identifies the responsible person, the precise trigger for updating each module, and the required handoff/tests.

## Temporary frontend API

Until the production services are available, run `python -m app.api.mock_server` from this directory. The working endpoints and request/response contracts for the preference form and product-card grid are in [app/api/MOCK_API.md](app/api/MOCK_API.md).

Do not create implementation files in `app/services/` until the owning member has agreed the endpoint contract in [app/api/API_CONTRACT.md](app/api/API_CONTRACT.md). The service folders are intentionally empty so Diwas, Tem, and Isaac can choose the files and internal design that suit their implementations.
