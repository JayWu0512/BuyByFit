"""Style tags from product photos (CLIP zero-shot), then re-embed so search matches on style.

    python -m app.services.product.vibe_tags              (from backend/; writes vibe_tags + re-embeds)
    python -m app.services.product.vibe_tags --dry-run    (prints a sample, writes nothing)

Neither ABO's copy nor the Cap3D captions say "japandi" or "boho", so text vectors can't match on style.
CLIP (sentence-transformers/clip-ViT-B-32) compares each product photo with several descriptions of each
style. Tags are relative: a product gets a tag when it looks more like that style than the catalogue
does on average (z-score per tag), so not every grey sofa becomes "modern". Up to 2 styles + 2 looks per
product from photos; materials (velvet, leather, rattan) come from the product text, which is more
reliable for those. Tags use a fixed vocabulary, so they compare cleanly and can be shown as chips.
"""
from __future__ import annotations

import argparse
import io
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url, upsert_embeddings

MODEL = "clip-ViT-B-32"
CACHE = Path.home() / "buybyfit-data" / "img-cache"

STYLES = {  # tag -> descriptions (averaged)
    "scandinavian": ["Scandinavian furniture, light wood, white and soft grey, simple and functional",
                     "Nordic style furniture with pale wood and clean simple shapes"],
    "japandi": ["Japandi furniture, low and minimal, light natural wood, clean lines, calm Japanese-Scandinavian style",
                "minimalist Japanese style furniture in natural oak with simple low forms"],
    "mid-century": ["mid-century modern furniture with tapered wooden legs and retro 1960s shapes",
                    "retro mid century furniture in walnut with angled peg legs"],
    "modern": ["sleek modern contemporary furniture with smooth surfaces and geometric shapes",
               "contemporary minimalist furniture, clean and polished"],
    "industrial": ["industrial furniture made of black metal and dark reclaimed wood",
                   "loft style furniture with black steel frame and pipes"],
    "boho": ["bohemian boho furniture, rattan, woven wicker, macrame, earthy patterned textiles",
             "boho style decor with jute, cane and natural woven textures"],
    "rustic": ["rustic furniture made of rough distressed wood, cabin style",
               "rustic reclaimed timber furniture with a weathered finish"],
    "farmhouse": ["farmhouse furniture, white painted or distressed wood, cottage country style",
                  "modern farmhouse style with shiplap white wood and black hardware"],
    "coastal": ["coastal beach house furniture, white, light blue, whitewashed wood, airy",
                "nautical seaside style furniture in white and soft blue"],
    "traditional": ["traditional classic furniture, ornate carved dark wood, rolled arms, tufted",
                    "antique style elegant furniture with carvings and turned legs"],
    "glam": ["glam furniture with velvet, gold and brass accents, mirrored and luxurious",
             "hollywood regency glamorous furniture, shiny gold metal and plush velvet"],
    "cute": ["cute playful kawaii decor, soft rounded shapes and pastel colors",
             "adorable whimsical kids room item, plush and cheerful"],
}
LOOKS = {
    "warm": ["warm cozy tones, caramel, terracotta, warm wood and amber light"],
    "airy": ["light airy bright pale furniture, white and cream"],
    "dark": ["dark moody furniture, black, charcoal and deep colors"],
    "colorful": ["bold colorful furniture in bright saturated colors"],
    "neutral": ["neutral beige, grey and off-white furniture"],
    "natural-wood": ["furniture made of visible natural wood grain"],
    "cozy": ["cozy soft plush upholstered furniture you sink into"],
}
CUTE_TYPES = {"PLUSH_TOY", "DECOR", "PILLOW", "BEAN_BAG_CHAIR", "FIGURINE", "VASE", "PLANTER", "CLOCK", "WALL_ART"}
MATERIAL_TAGS = [(r"velvet", "velvet"), (r"(?<!faux )leather(?!ette)|top[- ]grain", "leather"),
                 (r"rattan|wicker|cane|jute|seagrass|woven", "rattan"), (r"marble|travertine", "marble"),
                 (r"brass|gold", "brass"), (r"linen", "linen"), (r"boucl[eé]", "boucle")]


def fetch_image(url: str):
    from PIL import Image
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (re.sub(r"[^A-Za-z0-9._-]", "_", url.split("://", 1)[-1])[-150:])
    try:
        if not f.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "BuyByFit-catalogue/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                f.write_bytes(r.read())
        img = Image.open(io.BytesIO(f.read_bytes())).convert("RGB")
        img.thumbnail((336, 336))
        return img
    except Exception:
        return None


def tag_embeddings(model, groups: dict) -> tuple[list[str], np.ndarray]:
    names, vecs = [], []
    for tag, descs in groups.items():
        e = model.encode([f"a product photo of {d}" for d in descs], normalize_embeddings=True)
        v = e.mean(0)
        names.append(tag)
        vecs.append(v / np.linalg.norm(v))
    return names, np.stack(vecs)


def pick(scores: np.ndarray, names: list[str], k: int, z_min: float) -> list[list[str]]:
    """Relative tagging: z-score each tag over the catalogue, keep up to k tags per product with z >= z_min."""
    z = (scores - scores.mean(0)) / (scores.std(0) + 1e-9)
    out = []
    for row in z:
        order = np.argsort(-row)[:k]
        out.append([names[i] for i in order if row[i] >= z_min])
    return out


FIELDS = ["id", "title", "product_type", "style", "material", "color", "keywords", "description", "caption", "vibe_tags"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    from sentence_transformers import SentenceTransformer

    conn = psycopg2.connect(database_url(), connect_timeout=20)
    with conn, conn.cursor() as cur:
        cur.execute(f"select {', '.join(FIELDS)}, image_urls[1] from products where image_urls[1] is not null "
                    f"order by id {'limit %s' % int(args.limit) if args.limit else ''}")
        rows = cur.fetchall()
    conn.close()
    products = [dict(zip(FIELDS, r[:-1])) for r in rows]
    urls = [r[-1] for r in rows]
    print(f"{len(products)} products with a photo; fetching images ...")
    with ThreadPoolExecutor(16) as pool:
        images = list(pool.map(fetch_image, urls))
    ok = [i for i, im in enumerate(images) if im is not None]
    print(f"  {len(ok)} images loaded")

    model = SentenceTransformer(MODEL)
    img_vecs = model.encode([images[i] for i in ok], batch_size=64, normalize_embeddings=True, show_progress_bar=True)
    s_names, s_vecs = tag_embeddings(model, STYLES)
    l_names, l_vecs = tag_embeddings(model, LOOKS)
    styles = pick(img_vecs @ s_vecs.T, s_names, k=2, z_min=0.9)
    looks = pick(img_vecs @ l_vecs.T, l_names, k=2, z_min=1.0)

    tags_by_id = {}
    for j, i in enumerate(ok):
        p = products[i]
        text = " ".join(str(p.get(k) or "") for k in ("title", "material", "caption", "description")).lower()
        mats = [t for pat, t in MATERIAL_TAGS if re.search(pat, text)][:2]
        style = [s for s in styles[j] if s != "cute" or p["product_type"] in CUTE_TYPES]   # no "cute" dining chairs
        tags = list(dict.fromkeys(style + looks[j] + mats))
        if p["product_type"] == "PLUSH_TOY" and "cute" not in tags:
            tags.insert(0, "cute")
        tags_by_id[p["id"]] = tags

    counts: dict[str, int] = {}
    for t in tags_by_id.values():
        for x in t:
            counts[x] = counts.get(x, 0) + 1
    print("tag counts:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))
    if args.dry_run:
        for p in products[:: max(1, len(products) // 20)]:
            print(f"  {str(tags_by_id.get(p['id'])):<55} {p['title'][:60]}")
        return 0

    conn = psycopg2.connect(database_url(), connect_timeout=20)   # fresh connection: encoding took minutes
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, "update products p set vibe_tags = v.tags from (values %s) as v(id, tags) where p.id = v.id",
                           list(tags_by_id.items()), template="(%s, %s::text[])", page_size=1000)
            for p in products:
                p["vibe_tags"] = tags_by_id.get(p["id"], p["vibe_tags"])
            n = upsert_embeddings(cur, products)
            print(f"tagged {len(tags_by_id)} products; re-embedded {n}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
