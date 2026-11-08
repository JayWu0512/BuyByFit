# BuyByFit product collection worker

> Status: optional internal collection and normalization utility. It is not
> called by the customer-facing request path and is not a public marketplace,
> availability, checkout, or price-verification API.

A Cloudflare Worker that collects constrained product-source data and returns
normalized JSON or CSV. It has no database; callers own storage, validation,
deduplication, availability checks, and refresh policy.

Sources:
- **Home Depot**: product by 9-digit id, plus search → product list.
- **Any retailer page with schema.org `Product` JSON-LD** (pass `?url=`), e.g. as a fallback if Home Depot blocks Workers.

## Deploy

```bash
npm install
npx wrangler login
npx wrangler secret put API_PASSWORD      # enter the team password
npx wrangler deploy                       # prints https://buybyfit-scraper.<subdomain>.workers.dev
```

Local: put `API_PASSWORD=...` in `.dev.vars`, then `npm run dev`. Tests: `npm test`.

## Auth

Every endpoint except `/` needs the password, sent one of three ways:
- header `x-api-key: <password>`
- HTTP Basic auth (any username), so it works in a browser prompt
- `?key=<password>` (handy, but it ends up in logs and history)

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/` | Help + health (no auth) |
| GET | `/product?id=318046582` | One Home Depot product |
| GET | `/product?url=<product url>` | One product from any JSON-LD retailer |
| GET | `/search?q=sofa&page=1` | Home Depot product ids/urls for a search |
| POST | `/batch` `{"ids":[...],"urls":[...],"format":"json"\|"csv"}` | Up to 20 products |
| GET | `/collect?q=sofa&limit=10&format=csv` | Search + scrape top results in one call |

```bash
curl -H "x-api-key: $PW" "https://<worker>/product?id=318046582"
curl -H "x-api-key: $PW" "https://<worker>/collect?q=mid+century+sofa&limit=10&format=csv" > sofas.csv
```

## Product schema (contract for services B and C)

```json
{
  "id": "homedepot:318046582",
  "source": "homedepot",
  "source_id": "318046582",
  "url": "...",
  "title": "...", "brand": "...", "category": ["Furniture", "..."],
  "price": 649, "currency": "USD", "rating": 4.5, "review_count": 212,
  "description": "...",
  "image_urls": ["..."],
  "width_cm": 213.4, "depth_cm": 91.4, "height_cm": 83.8,
  "specs": [{ "name": "Product Width (in.)", "value": "84" }],
  "caption": null, "vibe_tags": null,
  "scraped_at": "2026-11-06T..."
}
```

- `id` is the join key across the SQL and vector stores.
- Dimensions are always cm. They come from spec fields first (package/seat/arm sizes are ignored), then from title/description text. A dimension stays `null` when it can't be found, so the room-fit filter should treat `null` as unknown, not as zero.
- `caption` / `vibe_tags` are left empty for the vision-LLM vibe step.

## Errors

`{ ok: false, error }` with HTTP 502, where `error` is one of:
- `blocked_by_site`: the retailer returned 403 or a bot challenge. Slow down or use another source.
- `http_error`: some other non-200 status.
- `no_product_data`: the page had no usable Product data.
- `fetch_failed`: a network error.

## Limits, legality, and data quality

- Batches are capped at 20 with a 400 ms gap between requests, and pages are cached at Cloudflare's edge for 1 hour.
- Home Depot may block Cloudflare IPs. Check `/product` first before building on it.
- Respect each site's terms and robots.txt. Keep pulls small and slow; this is a class prototype.
- Respect each site's rate limits and applicable law.
- A successful response is not proof that a product is available or that a
  price is current. Preserve collection time and source URL, then verify
  before publishing product data.
