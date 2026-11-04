# Frontend

Placeholder for the web client.

## Current API for development

Before the production backend exists, Jay can start the mock API with:

```bash
cd backend
python -m app.api.mock_server
```

Use `POST /api/v1/searches` for the first-page preference form and `GET /api/v1/searches/{search_id}/products` for the second-page product grid. Request and response examples are in [the mock API guide](../backend/app/api/MOCK_API.md); do not add fields to the UI contract without first updating [the API contract](../backend/app/api/API_CONTRACT.md).

Suggested feature ownership:

- `features/catalog`: product browsing and filters
- `features/recommendations`: ranked product results
- `features/room-upload`: image/measurement submission
- `features/room-preview`: 3D room visualization

Choose the UI framework before adding package manifests and build configuration.
