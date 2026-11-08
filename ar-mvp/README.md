# AR MVP: research prototype

> Status: standalone AR research prototype. It is not wired into the deployed
> Next.js application, Vercel deployment, or current room-restyling flow.
> Treat the commands and catalogue counts below as prototype instructions,
> not as a production service-level agreement.

# Say a vibe, see furniture in your room

Speak ("a cozy mid-century sofa that fits 230 by 100") → vibe search in Supabase (pgvector) with a room-fit filter → tap a result → **View in your room**, which places the real-size `.glb` on your floor through the live camera.

```text
phone mic ─ Web Speech API ─> text ─> POST /api/search ─> parse (vibe, W×D×H, type)
   ─> bge-small embedding ─> match_products(require_ar) in Supabase ─> cards
   ─> <model-viewer> ─> AR: WebXR / Scene Viewer (Android) · Quick Look (iPhone)
```

## Live mode: `/live` (talk while the camera is on)

Tap **Start camera + mic** once. After that you just talk, and the room updates without leaving the camera:

| Say | What happens |
|---|---|
| “a cozy mid-century sofa, a brass floor lamp and a teddy bear” | finds each one and lays them out side by side where you're pointing, without overlaps |
| “a cute bunny plushie” | adds one more piece next to the others |
| *(tap a piece)* | selects it (orange ring); the commands below act on it |
| “next” / “previous” | swaps the selected piece for its next or previous match, in the same spot |
| “replace it with a velvet armchair” / “… instead” | new search for the selected piece |
| “rotate”, “turn it around”, “rotate left” | +45°, 180°, −45° |
| “put it here” (or tap the floor) | moves the selected piece to the ring on the floor |
| “remove it” / “clear the room” | removes the selected piece / everything |

Splitting only happens where each part names a product, so “a black and white rug” stays one item.

- **Android Chrome + ARCore:** true WebXR AR with floor hit-testing, real scale and a world-locked position.
- **iPhone / others:** Safari has no WebXR, so you get the live camera feed with the model overlaid. There's no floor tracking: drag to turn it, and drag up or down to move it closer or farther.
- Desktop demo with no mic: `/live?demo=a cozy sofa`

## Run

From the repo root, with `backend/.env` holding `RELATIONAL_DATABASE_URL`:

```bash
pip install fastapi uvicorn psycopg2-binary sentence-transformers
python ar-mvp/prepare_models.py   # once: compresses ~47 models into ar-mvp/models (git-ignored), marks them AR-ready
python ar-mvp/server.py           # http://localhost:8080
```

Demo link with a preset query: `http://localhost:8080/?q=a velvet armchair 7 ft x 3 ft`

## On your phone (the mic and AR need HTTPS)

**Option A: quick tunnel (works for Android and iPhone).**
```bash
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8080
```
Open the `https://….trycloudflare.com` URL it prints on your phone. Anyone with that URL can use the app while the tunnel runs, so stop it when you're done.

**Option B: same Wi-Fi, Android only.** In Chrome, open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, add `http://<laptop LAN IP>:8080`, and relaunch. You may need to allow port 8080 through the Windows firewall.

## Device support

| | Voice | AR |
|---|---|---|
| Android, Chrome (ARCore phone) | yes | WebXR in-page, or Scene Viewer |
| iPhone, Safari (iOS 14.5+) | yes | Quick Look (USDZ generated on the fly from the GLB) |
| Desktop | Chrome/Edge yes | no, 3D preview only |

## Notes and limits

- **True size:** ABO models are in metres (checked: chair model 0.82×0.91×0.82 m vs listing 81×81×86 cm). `ar-scale="fixed"` stops pinch-resizing. If a model is more than 25% off its listing, the page rescales it.
- **One tap is required:** browsers only open AR from a tap, so voice finds the item and the "View in your room" button opens AR.
- **Catalog:** counts describe the prototype dataset at the time this document
  was written. Verify the connected Supabase project before relying on them.
- **AR-ready set:** only products with `products.ar_model_url` appear in AR (about 112 now: 72 ABO + 40 plush). To add more, run `prepare_models.py --per-type 2` and `python -m app.services.product.objaverse_import --limit 80` (from `backend/`).
- **Plushies** (`backend/app/services/product/objaverse_import.py`): Objaverse/Sketchfab models under CC0, CC BY or CC BY-SA only, with trademarked characters filtered out. Each one stores its author credit in `license`. The models have no real scale, so they're sized by category (a teddy bear is about 35 cm).
- Data and models: Amazon Berkeley Objects, © Amazon.com, CC BY 4.0. Objaverse models are credited to each author in `products.license`.
