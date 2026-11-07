# BuyByFit frontend

BuyByFit is a furniture-discovery MVP for people furnishing a real room. Rather than beginning with filters, visitors describe the room in their own words and then review a calm, Scandinavian-inspired catalogue of pieces that fit the brief.

The current app is a self-contained Next.js demo. It deliberately uses local mock data and fictional imagery; no backend, retailer, or AI recommendation service is called yet.

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
| `/discover` | Free-form room brief. A non-empty submission reveals the mock catalogue; voice dictation is offered when the browser supports the Web Speech API. |
| `/products/[id]` | Product detail, dimensions, materials, style, and a disabled `Buy it` action for the fictional catalogue. |

Search text and sorting are kept in tab-scoped session storage, so **Back to your search** returns to the same result state. Every valid brief currently returns the same 16 fictional products by design.

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
- All catalogue images, retailer references, descriptions, and prices are fictional. Replace them with licensed assets, verified product data, and real retailer URLs before release.
- `Buy it` remains unavailable until a verified product URL is supplied.

## Backend integration

The backend mock server and future API contract live in [`../backend/app/api/`](../backend/app/api/). The present frontend does **not** call those endpoints. When real search is ready, replace the local submit path in `src/components/discover-view.tsx` with the agreed API client and update the frontend handling, API contract, and mock guide together.

## Deploy on Vercel

The deployment repository is [`JayWu0512/buy-by-fit`](https://github.com/JayWu0512/buy-by-fit). The source repository publishes this directory to that repository's `main` branch through [the sync workflow](../.github/workflows/sync-vercel-deploy-repo.yml) after each merge to source `main`.

In Vercel, import `buy-by-fit` and use its repository root as the project root. Vercel auto-detects Next.js; use `npm ci` to install and `npm run build` to build. Node.js `>=20.9.0` is declared in `package.json`.
