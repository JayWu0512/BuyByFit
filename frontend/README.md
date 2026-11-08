# BuyByFit frontend

The frontend is a Next.js 15 application for room-first furniture discovery. People describe the space they want to create, browse ranked products, inspect a product in detail, and—when the Python service is configured—upload or capture a room photo for a restyled preview.

The browser only calls same-origin `/api/v1/*` routes. Those routes select or proxy server-side integrations, so a browser never receives a backend URL, a database key, or an embedding credential.

## Requirements and local development

Use Node.js 20.9 or later (Node 22 LTS is used in CI and Vercel).

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The local fictional catalogue works without any environment variables.

```bash
npm run typecheck
npm run build
```

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Brand story and entry point to discovery. |
| `/discover` | Room brief, optional voice dictation, budget, ranked results, and the optional room-restyling flow. |
| `/products/[id]` | Product page with facts, related items, retailer link when provided, and optional 3D/AR viewer. |
| `POST /api/v1/searches` | Server-only search gateway. |
| `/api/v1/rooms/*` | Server-only proxy routes for the room-visualization API. |

Search text, search results, sorting, and room-render progress are stored in tab-scoped session storage. They are not shared across browsers or written to a user account.

## Search resolution

`POST /api/v1/searches` resolves integrations in this order:

1. `RECOMMENDATION_API_URL` — proxy to the FastAPI recommendation endpoint.
2. `SUPABASE_URL` + `SUPABASE_ANON_KEY` — server-side semantic search against the Supabase `match_products` RPC and `products` table.
3. No configuration — rank the bundled fictional catalogue locally.

If a configured Supabase search fails, the route serves the local demo catalogue rather than failing the visitor's search. If `RECOMMENDATION_API_URL` is configured, its response and errors are passed through so an operational integration issue remains visible.

## Configuration

Copy [`.env.example`](.env.example) to `.env.local` for local work, or configure the same variables in Vercel. Every listed value is server-only.

| Variable | Required for | Notes |
| --- | --- | --- |
| `RECOMMENDATION_API_URL` | FastAPI-powered search | Service origin only, for example `https://api.example.com`; do not append `/api/v1/searches`. |
| `SUPABASE_URL` | Supabase catalogue search and real product pages | Used only if no FastAPI search URL is set. |
| `SUPABASE_ANON_KEY` | Supabase catalogue search and real product pages | Use a read-only/publishable key protected by Supabase RLS. |
| `ROOM_API_URL` | Room restyling | FastAPI room-service origin. Falls back to `RECOMMENDATION_API_URL` when omitted. |
| `AR_ASSET_BASE_URL` | Relative GLB assets | Optional public origin that serves paths stored in `ar_model_url`. |
| `EMBEDDING_DTYPE` | Supabase semantic search | Optional: `q8` (default) or `fp32` for the server-side embedding runtime. |

Never use `NEXT_PUBLIC_` for these values. Localhost addresses are only valid for local development and must not be used in a production Vercel environment.

## Catalogue and product data

Real records are read server-side from Supabase. The UI supports source titles, description, retailer URL, images, dimensions, material, color, style tags, price, a price estimate, and optional 3D/AR URLs. A retailer link appears only when the record provides `product_url`.

Price and availability are time-sensitive source data. Product pages should not be interpreted as a checkout flow or as a guarantee that a retailer listing remains available.

## Project map

```text
src/app/                   Pages and Next.js API proxy routes
src/components/            Discovery, product, room, and shared UI components
src/lib/api.ts             Browser search client and response mapping
src/lib/server/supabase.ts Server-only Supabase search/product adapter
src/lib/server/room-api.ts Server-only room-service forwarding helpers
src/types/                 Shared TypeScript types
public/                    Brand marks and fictional demo imagery
```

The visual system is documented in [DESIGN.md](DESIGN.md). Product scope and behaviour are documented in [PRODUCT.md](PRODUCT.md). The cross-service response contract lives in [../backend/app/api/API_CONTRACT.md](../backend/app/api/API_CONTRACT.md).

## Deployment

This directory is mirrored to [`JayWu0512/buy-by-fit`](https://github.com/JayWu0512/buy-by-fit) by the source repository's sync workflow. Import that mirror in Vercel with the Next.js preset, `npm ci`, and `npm run build`. See the root [README](../README.md) for mirror-token setup and release workflow.
