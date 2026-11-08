# BuyByFit architecture

## System overview

BuyByFit separates the customer-facing Next.js application from the services that hold catalogue data, perform recommendation, or process room images. The browser talks only to Next.js on the current origin; Next.js keeps integration configuration server-side.

```text
Browser
  └─ Next.js application
       ├─ POST /api/v1/searches
       │    ├─ FastAPI recommendation service (when RECOMMENDATION_API_URL is set)
       │    ├─ Supabase pgvector search (when Supabase is configured)
       │    └─ local fictional-catalogue ranking (fallback)
       ├─ /api/v1/rooms/* proxy routes
       │    └─ FastAPI room service → Vertex AI + private storage
       └─ /products/[id]
            ├─ local fictional product
            └─ Supabase product record
```

## Search path

1. The browser submits a JSON room brief and optional filters to the same-origin Next.js search route.
2. Next.js uses the configured FastAPI recommendation origin first. This lets the service own vector retrieval, filters, and result scoring.
3. Without that origin, Next.js can embed the brief server-side and call Supabase's `match_products` pgvector RPC. It then retrieves selected product records through PostgREST.
4. Without either integration—or if Supabase is temporarily unavailable—Next.js ranks the bundled fictional catalogue so the interface remains usable.
5. The browser maps the stable product-card contract to UI cards and retains the result state in session storage.

The public card shape is defined in [the API contract](../backend/app/api/API_CONTRACT.md). Both FastAPI and Supabase paths must preserve its fields and units.

## Room-visualization path

1. The visitor takes or uploads a JPEG/PNG room photo and may provide physical room width/depth.
2. The browser sends that multipart request to a same-origin Next.js room route.
3. Next.js forwards it to `ROOM_API_URL`, or to `RECOMMENDATION_API_URL` when both capabilities are deployed in the same FastAPI service.
4. The FastAPI room service stores the input privately and starts an asynchronous Vertex AI job. When the optional Thinking Machines reviewer is configured, its fine-tuned Inkling 2 Small + LoRA model critiques the original room and supplies the Gemini design brief.
5. After the selected render is ready, the same expert can return up to three style-only ideas; it does not recommend products. The browser polls the same-origin status route, displays the completed render through a proxy route, and can send structured feedback.

Room images and renders are user-provided/generated content. They belong in private storage, not Git or a public product catalogue. Exact placement is best when the visitor supplies real room measurements; camera-only scale is an estimate.

## Service boundaries

| Boundary | Responsibility | Must not do |
| --- | --- | --- |
| Next.js frontend | Interaction design, browser session state, same-origin gateway, product presentation | Expose service origins/secrets or write directly to Supabase from the browser. |
| Product/catalogue layer | Normalize source product fields, preserve source URLs/media/dimensions, refresh source data | Treat a stale price or listing as verified current inventory. |
| Recommendation service | Embed queries, apply room/price/category constraints, rank products | Own retailer crawling or room-image processing. |
| Room service | Validate room uploads, run the asynchronous rendering pipeline, coordinate the optional fine-tuned design reviewer, retain job/result metadata and feedback | Make the browser communicate with Vertex AI or Tinker directly. |
| Supabase/PostgreSQL + pgvector | Product source of truth, embeddings, indexed similarity/fit queries | Hold client-side secrets or bypass RLS. |

## Reliability and security rules

- All browser APIs are same-origin `/api/v1/*` endpoints.
- Environment variables for Supabase and backend origins are server-only.
- The local fictional catalogue is deliberate fallback content, not live inventory.
- Use explicit source metadata for retailer URL, collection time, price, and price estimate. Availability and prices must be refreshed outside the request path.
- Contract changes require updates to [API_CONTRACT.md](../backend/app/api/API_CONTRACT.md), the clients, and tests in the same change.
- Generated room files, database exports, API keys, and `.env` files never belong in Git.
