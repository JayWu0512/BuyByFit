"""Import cute stuff (plushies, teddy bears, piggy banks, ...) from Objaverse into the product catalog.

    python -m app.services.product.objaverse_import --limit 40          (from backend/)

Objaverse (https://objaverse.allenai.org) is ~800k Sketchfab models with per-model Creative Commons
licenses. We keep only CC0 / CC BY / CC BY-SA, drop trademarked characters, and credit each author.
The models have no real-world scale, so each one is given a believable size for its category
(e.g. a teddy bear ~35 cm) and the dims are written into the product row; the AR page rescales to them.

Writes: products rows (source='objaverse', no price), embeddings, and AR-ready models in ar-mvp/models.
"""
from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from app.services.product import glb_tools
from app.services.product.index_products import database_url, upsert_embeddings, upsert_products

REPO = Path(__file__).resolve().parents[4]
MODELS_DIR = REPO / "ar-mvp" / "models"

# LVIS category -> (our product_type, typical largest dimension in metres)
CATEGORIES = {
    "teddy_bear": ("PLUSH_TOY", 0.35), "rag_doll": ("PLUSH_TOY", 0.30), "doll": ("PLUSH_TOY", 0.30),
    "toy": ("PLUSH_TOY", 0.30), "piggy_bank": ("DECOR", 0.16),
    **{a: ("PLUSH_TOY", 0.30) for a in ["rabbit", "kitten", "cat", "puppy", "dog", "pug-dog", "bulldog", "frog",
                                       "penguin", "owl", "elephant", "giant_panda", "bear", "polar_bear"]},
    "duckling": ("PLUSH_TOY", 0.20), "duck": ("PLUSH_TOY", 0.25),
}
ANIMALS = {c for c in CATEGORIES if c not in ("teddy_bear", "rag_doll", "doll", "toy", "piggy_bank")}
OK_LICENSES = {"cc0": "CC0 1.0", "by": "CC BY 4.0", "by-sa": "CC BY-SA 4.0"}
PLUSH_WORDS = re.compile(r"plush|stuffed|teddy|soft ?toy|cuddl|kawaii|chibi|cute|amigurumi|crochet|knit|squish|toy|doll", re.I)
# other people's characters / brands: not ours to put in a catalog
TRADEMARKS = re.compile(
    r"fumo|touhou|東方|freddy|fnaf|five nights|hello kitty|sanrio|thomas the tank|sims|pok[eé]mon|pikachu|disney|"
    r"mickey|minnie|winnie|pooh|mario|sonic|minecraft|roblox|kirby|totoro|ghibli|stitch|marvel|star wars|"
    r"squishmallow|care bear|paddington|peppa|bluey|sesame|elmo|garfield|snoopy|spongebob|genshin|among us",
    re.I)
MAX_FACES = 150_000


def candidates() -> list[dict]:
    import objaverse
    lvis = objaverse.load_lvis_annotations()
    cat_of = {u: c for c in CATEGORIES for u in lvis.get(c, [])}
    ann = objaverse.load_annotations(list(cat_of))
    out = []
    for uid, a in ann.items():
        cat, lic = cat_of[uid], (a.get("license") or "").lower()
        text = " ".join([a.get("name") or "", a.get("description") or ""] + [t["name"] for t in a.get("tags", [])])
        if lic not in OK_LICENSES or (a.get("faceCount") or 0) > MAX_FACES or TRADEMARKS.search(text):
            continue
        if cat in ANIMALS and not PLUSH_WORDS.search(text):      # a realistic cat isn't a plushie
            continue
        if cat == "toy" and not re.search(r"plush|stuffed|teddy|soft|cute|kawaii|bear|bunny|duck|cat|dog", text, re.I):
            continue
        thumbs = sorted((a.get("thumbnails") or {}).get("images", []), key=lambda t: -t.get("width", 0))
        thumb = next((t["url"] for t in thumbs if t.get("width", 0) <= 1024), thumbs[0]["url"] if thumbs else None)
        out.append({"uid": uid, "cat": cat, "a": a, "lic": lic, "thumb": thumb,
                    "plushy": bool(re.search(r"plush|stuffed|teddy|soft|cuddl|amigurumi|crochet|knit", text, re.I))})
    out.sort(key=lambda r: (not r["plushy"], -(r["a"].get("likeCount") or 0)))
    return out


def to_product(c: dict, dims_cm: tuple[float, float, float], now: str) -> dict:
    a = c["a"]
    ptype, _ = CATEGORIES[c["cat"]]
    author = (a.get("user") or {}).get("displayName") or "unknown"
    tags = [t["name"] for t in a.get("tags", [])][:15]
    kind = "plush toy" if ptype == "PLUSH_TOY" else c["cat"].replace("_", " ")
    name = (a.get("name") or kind).strip()
    title = name if re.search(r"plush|teddy|toy|doll|stuff", name, re.I) or ptype != "PLUSH_TOY" else f"{name} plush toy"
    return {
        "id": f"objaverse:{c['uid']}", "source": "objaverse", "source_id": c["uid"], "url": a.get("viewerUrl"),
        "title": title[:200], "brand": None, "product_type": ptype,
        "category": ["Home", "Decor", "Plush Toys" if ptype == "PLUSH_TOY" else "Decorative Accents"],
        "style": "Cute", "material": "Plush fabric" if ptype == "PLUSH_TOY" else None, "color": None,
        "price": None, "currency": None,
        "description": (a.get("description") or "").strip()[:1500] or f"A cute {kind}.",
        "keywords": sorted({kind, "cute", c["cat"].replace("_", " "), *tags}),
        "image_urls": [c["thumb"]] if c["thumb"] else [],
        "model_3d_url": None, "width_cm": dims_cm[0], "depth_cm": dims_cm[2], "height_cm": dims_cm[1],
        "caption": None, "vibe_tags": None,
        "license": f"{OK_LICENSES[c['lic']]}, by {author} on Sketchfab (via Objaverse)",
        "scraped_at": now,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--max-mb", type=float, default=25, help="skip downloads bigger than this")
    args = ap.parse_args(argv)
    import objaverse

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    picked = candidates()[: args.limit * 2]          # extra in case some fail to download/convert
    print(f"{len(picked)} candidates; downloading ...")
    paths = objaverse.load_objects([c["uid"] for c in picked], download_processes=4)

    products, ar_urls = [], {}
    for c in picked:
        if len(products) >= args.limit:
            break
        raw = Path(paths.get(c["uid"], ""))
        if not raw.is_file() or raw.stat().st_size > args.max_mb * 1e6:
            continue
        out = MODELS_DIR / f"objaverse-{c['uid']}.glb"
        try:
            if not out.exists():
                glb_tools.optimize_glb(raw, out)
            x, y, z = glb_tools.glb_bbox(out)
        except Exception as e:
            print(f"  skip {c['uid']}: {type(e).__name__}")
            out.unlink(missing_ok=True)
            continue
        biggest = max(x, y, z)
        if biggest <= 0:
            continue
        s = CATEGORIES[c["cat"]][1] / biggest                    # believable real size
        p = to_product(c, (round(x * s * 100, 1), round(y * s * 100, 1), round(z * s * 100, 1)), now)
        products.append(p)
        ar_urls[p["id"]] = f"/models/{out.name}"
        print(f"  ok  {p['width_cm']:>5}x{p['depth_cm']:>5}x{p['height_cm']:>5} cm  {p['title'][:60]}")

    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            upsert_products(cur, products)
            cur.executemany("update products set ar_model_url = %s where id = %s", [(u, i) for i, u in ar_urls.items()])
            n = upsert_embeddings(cur, products)
    finally:
        conn.close()
    print(f"imported {len(products)} cute items ({n} embedded), AR models in {MODELS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
