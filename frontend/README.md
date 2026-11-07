# BuyByFit frontend

BuyByFit is a furniture-discovery MVP for people furnishing a real room. Rather than beginning with filters, visitors describe the room in their own words and then review a calm, Scandinavian-inspired catalogue of pieces that fit the brief.

The app calls its same-origin search endpoint, which works as a Vercel
Serverless Function. By default it ranks the small fictional catalogue so a
demo never depends on an external service. When `RECOMMENDATION_API_URL` is
configured server-side, it proxies to the FastAPI recommendation service for
pgvector-ranked catalogue results and real source metadata.

## Run locally

Requirements: Node.js 20.9 or later and npm.

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Useful checks:

```bash
npm run typecheck
npm run build
```

## Routes and behavior

| Route | Purpose |
| --- | --- |
| `/` | Brand introduction and product principles. |
| `/discover` | Free-form room brief. A non-empty submission reveals ranked products; voice dictation is offered when the browser supports the Web Speech API. Live products open their source retailer in a new tab. |
| `/products/[id]` | Product detail, dimensions, materials, style, and a `Buy it` action for local catalogue items that have a verified retailer URL. |

Search text and sorting are kept in tab-scoped session storage, so **Back to your search** returns to the same result state. The serverless fallback returns its 16 fictional products; the configured FastAPI service returns semantic matches from the imported catalogue.

## Project map

```text
src/app/                   Route pages, shared layout, and global styles
src/components/            Header, footer, logo, discovery view, and product cards
src/lib/mock-furniture.ts  Local fictional catalogue
src/lib/catalog.ts         Product lookup and catalogue helpers
src/types/                 Shared TypeScript types
public/images/             Fictional demonstration photography
public/brand-mark.svg      BuyByFit browser icon and reusable mark
```

## Design and content rules

- The visual system is documented in [DESIGN.md](DESIGN.md); it uses warm paper, oat, sage, timber, and soft asymmetric image corners.
- The product intent and MVP boundaries are documented in [PRODUCT.md](PRODUCT.md).
- The fallback catalogue is fictional. Live result data is passed through from local `infra/` CSV exports, including its image and product-source URLs. Verify availability, pricing, and retailer destination before presenting it as a production marketplace.
- `Buy it` opens a retailer only when a product record supplies `product_url`; otherwise no false purchase action is shown.

## Backend integration

The search UI calls same-origin `POST /api/v1/searches`. The Next.js route at `src/app/api/v1/searches/route.ts` is a Vercel Serverless Function that ranks the local fictional catalogue for this MVP, so it works without a separate backend deployment.

For the Python/FastAPI recommendation service, load the catalogue and its vectors from `infra/` as described in [../infra/README.md](../infra/README.md), deploy the backend separately, and set server-only `RECOMMENDATION_API_URL` in local or Vercel environment variables. The same browser endpoint then proxies requests to that backend without changing client code. Use only the backend origin, for example `https://buybyfit-api.example.com`—do not add `/api/v1/searches` and do not expose it through a `NEXT_PUBLIC_` variable.

## Deploy on Vercel

The deployment repository is [`JayWu0512/buy-by-fit`](https://github.com/JayWu0512/buy-by-fit). The source repository publishes this directory to that repository's `main` branch through [the sync workflow](../.github/workflows/sync-vercel-deploy-repo.yml) after each merge to source `main`.

In Vercel, import `buy-by-fit` and use its repository root as the project root. Select the **Next.js** framework preset, leave Output Directory blank, use Node.js 22 LTS, install with `npm ci`, and build with `npm run build`. Node.js `>=20.9.0` is declared in `package.json`.
