# Backend engineering workflow

This document is the working agreement for changes to BuyByFit's backend-facing contracts. It is role-based so responsibilities remain clear as contributors change.

## Service boundaries

| Area | Owns | Does not own |
| --- | --- | --- |
| Catalogue | Source normalization, product fields, dimensions, price/estimate provenance, import/index jobs | Browser UI, live retailer scraping in request handlers, recommendation scoring. |
| Recommendation | Query embeddings, constraint parsing, vector retrieval, ranking, result explanations | Source-of-truth product curation or room-image processing. |
| Room visualization | Upload validation, private media storage, job lifecycle, rendering/provider integration, feedback records | Direct browser/provider communication or public media hosting. |
| Frontend gateway | Same-origin routes, browser experience, response mapping, session state | Backend credentials, direct database writes, private provider access. |

## Contract-first procedure

1. Write or update the endpoint's request, response, limits, error status, and ownership in [app/api/API_CONTRACT.md](app/api/API_CONTRACT.md).
2. Confirm the change with every affected boundary, including the frontend when a browser-consumed field changes.
3. Implement the service and route changes in the same pull request.
4. Add or update validation, behavior, and field-mapping tests.
5. Update the relevant README/architecture document when deployment topology, configuration, or operational behavior changes.

Do not silently remove, rename, or change the units of a browser-consumed response field.

## Implementation rules

- Public endpoints are versioned under /api/v1.
- Error responses use the JSON shape error.message and error.status.
- Dimensions are centimetres; unknown dimensions are null, never zero.
- A verified source price and a modelled/estimated price are separate data concepts.
- Routes validate and translate HTTP. Database, ranking, storage, and provider work stays in the corresponding service module.
- Use server-side configuration for credentials. Never log values of connection strings, API keys, signed URLs, or uploaded room photos.
- Files created from room uploads/renders belong in private storage and must have retention/access policies outside Git.

## Pull-request checklist

- [ ] The API contract reflects any externally observable change.
- [ ] Request validation, error handling, and response mapping have tests.
- [ ] Product/source data retains its provenance and units.
- [ ] New environment variables are documented with a non-secret example.
- [ ] Generated files, databases, credentials, and .env files are excluded.
- [ ] Frontend and documentation changes are included when they are affected.

## Local verification

    cd backend
    python -m compileall -q app scripts
    python -m unittest discover -s tests -p "test_*.py"

For frontend-facing changes, also run the checks in [../frontend/README.md](../frontend/README.md).
