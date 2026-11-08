# Historical handoff: product data → vector DB

> Archived planning note written on 2026-11-06. It captures a branch-specific
> proposal and may not match current code, deployment, providers, catalogue
> counts, or ownership. Use README.md, docs/architecture.md,
> backend/README.md, and backend/app/api/API_CONTRACT.md as current sources of
> truth. Keep this file for rationale only; do not implement it verbatim
> without validating the present repository and contracts.

Owner: Diwas (A, product service). Written 2026-11-06 from a claude.ai session, for a Claude Code session to continue.
Branch: `feat/product-scraper-worker` (4 commits on top of `main` @ `89d32cd`). Not pushed yet: the Claude GitHub app isn't installed on `JayWu0512/BuyByFit`, so push from a local clone.

## Product idea (what this has to support)

1. A user **speaks** the vibe they want ("warm mid-century living room, lots of wood, cozy").
2. We find **products whose vibe matches**, filtered to what **physically fits** the room.
3. Products end up **in a 3D space**. See open question 1: this means either a 3D vibe map or placing them in the 3D room.

## What already exists on this branch

| Path | What it is | Status |
|---|---|---|
| `scraper-worker/` | Cloudflare Worker: scraping API + catalog web app (password via `API_PASSWORD` secret) | Deployed on a temporary Cloudflare account (`buybyfit-scraper.foggy-corn.workers.dev`), which expires unless claimed. 7 node tests pass (`npm test`). |
| `scraper-worker/src/abo.js` | `GET /abo?shard=0..f&types=SOFA,CHAIR&limit=&offset=&dims=1&3d=1&format=csv`: streams Amazon Berkeley Objects listings, returns furniture with image + `.glb` URLs | Tested with mocks only; live result not confirmed yet |
| `scraper-worker/src/scrape.js` | `/product?id=|url=`, `/search`, `/collect` for Home Depot + any schema.org Product page | **Home Depot returns 403 from Cloudflare (confirmed live).** Generic `?url=` path is untested live. |
| `scraper-worker/src/app.html` | Mobile-friendly UI: browse ABO by type, room-fit filter (W/D/H cm), CSV/JSON download | Layout checked in a headless browser with mock data |
| `backend/app/services/product/abo_import.py` | Stdlib Python: downloads ABO (~83 MB listings + metadata), writes `products.json` / `products.csv` | 2 pytest tests pass on a fake ABO cache; not run on the real dataset yet |
| `.github/workflows/deploy-scraper.yml` | Deploys the Worker on push to `main` (paths `scraper-worker/**`) | Needs repo secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `API_PASSWORD` |

Decisions already made:
- **ABO is the main catalog** (CC BY 4.0, credit "Amazon.com"). It has dims, images, and ~8k 3D models. It has no prices.
- **Home Depot is dropped** for direct scraping, because it blocks Cloudflare. If it's needed, use a paid service like Apify, behind the same `/product` route.
- No DB inside the Worker; it stays stateless. Persistence happens in the Python backend.

## Normalized product record (produced by both the Worker and `abo_import.py`)

```json
{ "id": "abo:B075X4QMX3", "source": "abo", "source_id": "B075X4QMX3", "url": "...",
  "title": "...", "brand": "...", "product_type": "SOFA", "category": ["Furniture", "..."],
  "style": "Mid-Century Modern", "material": "...", "color": "Grey",
  "price": null, "currency": null, "description": "...", "keywords": ["..."],
  "image_urls": ["..."], "model_3d_url": "https://.../x.glb",
  "width_cm": 221.0, "depth_cm": 95.9, "height_cm": 83.8,
  "caption": null, "vibe_tags": null, "license": "CC BY 4.0 ...", "scraped_at": "..." }
```

Frontend card contract (`API_CONTRACT.md` rule 5) needs: `id, name, price, currency, image_url, product_url, dimensions_cm{width,depth,height}, style_tags, match_score, match_reason`. Mapping: `name←title`, `image_url←image_urls[0]`, `product_url←url`, `style_tags←vibe_tags`. `match_*` come from B's ranking.

## Proposed design: vectors

```text
ABO / scraper ──> normalize (exists) ──> enrich vibe (NEW) ──> embed (NEW) ──> store
                                                                         ├─ Postgres: product row (source of truth)
                                                                         └─ Qdrant: vectors + filter payload
voice ──> transcript ──> embed query ──> Qdrant search (fit filter) ──> rerank (B) ──> cards / 3D
```

1. **Enrich (product service, A).** For each product, send image 1 + title/description/style/material to a vision LLM. Get back:
   - `caption`: 1–2 plain sentences on what it looks like.
   - `vibe_tags`: 3–6 tags chosen **only** from a fixed vocabulary, so tags compare cleanly. Starting list: scandinavian, mid-century, modern, minimal, industrial, boho, rustic, farmhouse, coastal, traditional, glam, japandi, cozy, warm, airy, dark, natural-wood, velvet, leather, colorful, neutral.
   - `colors`, `materials`, `room`: living / bedroom / dining / office / outdoor.

   Cache the results keyed by `id` + model version, so a rerun doesn't pay twice. A DSPy/MIPROv2 prompt-tuning pass (it's on the whiteboard) fits here later.
2. **Vibe document.** Build one string per product, e.g. `"{title}. {caption} Vibe: {tags}. Materials: … Colors: … Room: …"`. This is what the text vector represents.
3. **Embed.** Use two named vectors per product:
   - `text`: a sentence-embedding model over the vibe document. The user's spoken query embeds with the same model.
   - `image`: CLIP-style over image 1, so "show me things like this photo" works later.

   Store `embedding_model` and `embedding_version` in the payload; `vector.py` says embeddings are versioned.
4. **Store in Qdrant** (`.env.example` already has `VECTOR_DATABASE_URL=http://localhost:6333`). Use collection `products_v1`. Qdrant point IDs must be UUIDs, so use `uuid5(NAMESPACE_URL, id)`, with the payload holding `product_id`. Payload fields for filtering: `product_type`, `width_cm`, `depth_cm`, `height_cm`, `has_3d`, `price`, `vibe_tags`, `source`. Index the numeric ones so the room-fit filter (`width_cm <= room_w` …) runs inside the vector search. Products with unknown dims must not pass a fit filter silently.
5. **Postgres** keeps the full record. The vector store holds vectors + filter payload only, matching the team rule in `WORKFLOW.md`.
6. **3D placement data** is already captured: `model_3d_url` (`.glb`) + dims in cm. The 3D service (C, Isaac) consumes these.

## Team rules to respect (from `backend/WORKFLOW.md` and `API_CONTRACT.md`)

- `app/db/vector.py` is owned by **Tem (B)**. Agree the collection name, vector names/dims, point-ID scheme and payload fields with Tem *before* writing to it. Product-side code (enrich, embed, upsert calls) lives in `app/services/product/`.
- `app/db/relational.py` product tables are owned by A (you). Isaac (C) needs A's review for shared changes.
- **Contract first:** add the Product detail/catalog request/response to `API_CONTRACT.md` before creating endpoints. Notify B of ranking fields and D of UI fields.
- New env vars go in both `.env.example` files with safe examples, plus `app/core/config.py`. Never commit keys.
- Tests in the same PR (`backend/tests/`).
- `abo_import.py` was added to `app/services/product/` before a contract was agreed. Mention that in the PR, or move it to `scripts/` if Jay prefers.

## Suggested task list for Claude Code

1. Fetch the branch from the bundle, run `cd scraper-worker && npm test` and `cd backend && python -m pytest`.
2. Run `abo_import.py --require-dims --limit 2000` on real data. Check the counts with full dims and with 3D models, and spot-check 10 records' dimensions against amazon.com.
3. Draft the Product contract + vector payload spec in `API_CONTRACT.md` and send it to Tem/Jay.
4. Implement `app/services/product/enrich.py` (vision LLM → caption, vibe_tags, colors, materials, room) with an on-disk cache and a fixed tag vocabulary. Add tests with a stubbed LLM.
5. Implement `app/services/product/embed.py` (vibe document builder + text and image embeddings) and an `index_products.py` CLI: JSON → Postgres upsert + Qdrant upsert. Use `docker run -p 6333:6333 qdrant/qdrant` locally.
6. Write a smoke script: query "cozy warm mid-century living room" with a fit filter of 230×100 cm. The top 10 should look on-vibe and fit, so eyeball them.
7. If the "3D space" means a vibe map, add a UMAP/PCA projection to 3D, store `vibe_xyz` in the payload, and give the web app a small three.js view.

## Open questions (ask Diwas before building)

1. **"Put products in a 3D space"**: does this mean (a) a 3D **vibe map**, with products placed by embedding similarity so the spoken query lands as a point among them, or (b) **placing products inside the user's 3D room** (Isaac's service, using `.glb` + dims)? Possibly both.
2. Which models and keys: hosted (OpenAI/Anthropic embeddings + vision) or open-source local (sentence-transformers + open_clip)? This affects cost and the class demo.
3. Where does speech-to-text happen: browser Web Speech API, Whisper, or the frontend team?
4. Catalog size for the demo, e.g. 2k items with full dims vs all ABO furniture.
5. Prices: ABO has none. Is that OK for the demo, or should a priced source be blended in?
