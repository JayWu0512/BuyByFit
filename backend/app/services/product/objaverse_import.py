"""Import 3D furniture, decor and plushies from Objaverse into the catalogue (with vectors and 3D models).

    python -m app.services.product.objaverse_import --set furniture --per-category 12   (from backend/)
    python -m app.services.product.objaverse_import --set plush --limit 40

Objaverse (https://objaverse.allenai.org) is ~800k Sketchfab models with per-model Creative Commons
licences. We keep only CC0 / CC BY / CC BY-SA, drop trademarked characters and whole-room scenes, and
credit each author in `license`.

Per product:
- description for the vibe vector: Cap3D's automatic caption of the 3D object (tiange/Cap3D, ODC-By)
  plus the model's own title, tags and description
- size: the models have no real-world scale, so each is scaled to a typical size for its category
  (a sofa ~200 cm wide), keeping its proportions. dims_estimated = true, and model_scale is the factor
  that brings model_3d_url to that size; models whose proportions are implausible are skipped
- model_3d_url: the public Objaverse file on Hugging Face (loads anywhere, incl. Vercel)
- ar_model_url: compressed copy in ar-mvp/models (1K textures, Draco) for phones and the room designer
- embedding: same model/version as the rest of the catalogue, so it's searchable immediately
Prices are filled afterwards by price_estimate.py.
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from app.services.product import glb_tools
from app.services.product.index_products import database_url, upsert_embeddings, upsert_products

REPO = Path(__file__).resolve().parents[4]
MODELS_DIR = REPO / "ar-mvp" / "models"
HF_BASE = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/"

# LVIS category -> (product_type, typical (width, depth, height) in cm, display noun)
FURNITURE = {
    "sofa": ("SOFA", (200, 90, 85), "sofa"), "sofa_bed": ("SOFA", (200, 95, 85), "sofa bed"),
    "futon": ("SOFA", (190, 90, 80), "futon"),
    "armchair": ("CHAIR", (85, 85, 85), "armchair"), "chair": ("CHAIR", (55, 55, 85), "chair"),
    "rocking_chair": ("CHAIR", (65, 90, 100), "rocking chair"), "folding_chair": ("CHAIR", (45, 50, 80), "folding chair"),
    "deck_chair": ("CHAIR", (60, 100, 90), "lounge chair"),
    "table": ("TABLE", (120, 75, 75), "table"), "dining_table": ("TABLE", (160, 90, 75), "dining table"),
    "kitchen_table": ("TABLE", (120, 80, 75), "kitchen table"), "coffee_table": ("TABLE", (110, 60, 45), "coffee table"),
    "desk": ("DESK", (130, 65, 75), "desk"),
    "bed": ("BED", (160, 210, 100), "bed"), "bunk_bed": ("BED", (100, 200, 170), "bunk bed"), "crib": ("BED", (70, 130, 90), "crib"),
    "bookcase": ("SHELF", (90, 35, 180), "bookcase"), "dresser": ("DRESSER", (120, 50, 85), "dresser"),
    "cabinet": ("CABINET", (90, 45, 90), "cabinet"), "armoire": ("CABINET", (100, 60, 190), "armoire"),
    "wardrobe": ("CABINET", (100, 60, 190), "wardrobe"),
    "bench": ("BENCH", (120, 40, 45), "bench"), "stool": ("STOOL_SEATING", (40, 40, 65), "stool"),
    "footstool": ("OTTOMAN", (45, 35, 40), "footstool"), "ottoman": ("OTTOMAN", (60, 60, 45), "ottoman"),
    "beanbag": ("BEAN_BAG_CHAIR", (90, 90, 80), "bean bag"),
    "table_lamp": ("LAMP", (30, 30, 50), "table lamp"), "lamp": ("LAMP", (35, 35, 150), "lamp"),
    "chandelier": ("LIGHT_FIXTURE", (60, 60, 60), "chandelier"),
    "vase": ("VASE", (20, 20, 35), "vase"), "flowerpot": ("PLANTER", (30, 30, 35), "planter"),
    "cushion": ("PILLOW", (45, 15, 45), "cushion"), "pillow": ("PILLOW", (50, 15, 35), "pillow"),
    "mirror": ("HOME_MIRROR", (60, 4, 90), "mirror"), "wall_clock": ("CLOCK", (35, 5, 35), "wall clock"),
    "clock": ("CLOCK", (30, 10, 30), "clock"), "basket": ("BASKET", (40, 40, 35), "basket"),
    "candle_holder": ("CANDLE_HOLDER", (12, 12, 25), "candle holder"), "painting": ("WALL_ART", (80, 3, 60), "wall art"),
    "runner_(carpet)": ("RUG", (240, 80, 1), "runner rug"),
}
PLUSH = {
    "teddy_bear": ("PLUSH_TOY", (28, 22, 35), "teddy bear"), "rag_doll": ("PLUSH_TOY", (20, 12, 30), "rag doll"),
    "doll": ("PLUSH_TOY", (20, 12, 30), "doll"), "toy": ("PLUSH_TOY", (25, 20, 30), "plush toy"),
    "piggy_bank": ("DECOR", (15, 10, 13), "piggy bank"),
    **{a: ("PLUSH_TOY", (25, 20, 30), "plush toy") for a in ["rabbit", "kitten", "cat", "puppy", "dog", "pug-dog", "bulldog",
                                                              "frog", "penguin", "owl", "elephant", "giant_panda", "bear",
                                                              "polar_bear", "duckling", "duck"]},
}
ANIMALS = {c for c in PLUSH if PLUSH[c][2] == "plush toy" and c != "toy"}
OK_LICENSES = {"cc0": "CC0 1.0", "by": "CC BY 4.0", "by-sa": "CC BY-SA 4.0"}
PLUSH_WORDS = re.compile(r"plush|stuffed|teddy|soft ?toy|cuddl|kawaii|chibi|cute|amigurumi|crochet|knit|squish|toy|doll", re.I)
TRADEMARKS = re.compile(
    r"fumo|touhou|東方|freddy|fnaf|five nights|hello kitty|sanrio|thomas the tank|sims|pok[eé]mon|pikachu|disney|"
    r"mickey|minnie|winnie|pooh|mario|sonic|minecraft|roblox|kirby|totoro|ghibli|stitch|marvel|star wars|"
    r"squishmallow|care bear|paddington|peppa|bluey|sesame|elmo|garfield|snoopy|spongebob|genshin|among us|"
    r"ikea|eames|herman miller|knoll|vitra|cassina|barcelona chair|wassily|starbucks|coca|harry potter|hogwarts",
    re.I)
# whole scenes / multi-object packs aren't a product
SCENES = re.compile(r"\b(room|scene|interior|house|home|set|collection|pack|kit|bundle|environment|apartment|"
                    r"diorama|office|lobby|studio|level|map|asset ?pack|props)\b", re.I)
MAX_FACES = 150_000

# Objaverse's LVIS labels are noisy ("Control Joystick Case" tagged mirror). For furniture, the Cap3D caption
# must name the thing, or the product isn't kept.
CAPTION_CONFIRMS = {
    "SOFA": r"sofa|couch|loveseat|settee|sectional|futon|daybed", "CHAIR": r"chair|armchair|recliner|seat",
    "TABLE": r"table", "DESK": r"desk|table|workstation", "BED": r"\bbed|crib|cot\b|bunk",
    "SHELF": r"shel(f|ves)|bookcase|bookshelf", "DRESSER": r"dresser|drawers?|chest",
    "CABINET": r"cabinet|wardrobe|armoire|cupboard|closet|sideboard", "BENCH": r"bench",
    "STOOL_SEATING": r"stool", "OTTOMAN": r"ottoman|footstool|pouf|stool|footrest",
    "BEAN_BAG_CHAIR": r"bean ?bag|beanbag|pouf|cushion|floor seat", "LAMP": r"lamp|light",
    "LIGHT_FIXTURE": r"chandelier|light|lamp|pendant", "VASE": r"vase", "PLANTER": r"\bpot\b|planter|plant|flowerpot",
    "PILLOW": r"pillow|cushion", "HOME_MIRROR": r"mirror", "CLOCK": r"clock", "BASKET": r"basket",
    "CANDLE_HOLDER": r"candle", "WALL_ART": r"painting|picture|frame|canvas|portrait|artwork|art\b",
    "RUG": r"\brug|carpet|runner|\bmat\b",
}
# not something you'd sell: damaged / grim / food / props
UNSELLABLE = re.compile(r"broken|damaged|dusty|rusty|rusted|stained|dirty|abandoned|destroyed|ruined|rotten|"
                        r"bloody|blood|zombie|horror|creepy|skull|weapon|gun|bread|food|fruit|vegetable|cake|"
                        r"meat|steampunk gear|gears|cogwheel|joystick|controller", re.I)


def captions(uids: set[str]) -> dict[str, str]:
    """Cap3D automatic captions (one sentence describing the 3D object) for the given Objaverse uids."""
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download("tiange/Cap3D", "Cap3D_automated_Objaverse_full.csv", repo_type="dataset")
    except Exception as e:  # captions improve vectors but aren't required
        print(f"  (no Cap3D captions: {type(e).__name__})")
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] in uids:
                out[row[0]] = row[1].strip()
    return out


def candidates(cats: dict, per_category: int | None, limit: int | None) -> list[dict]:
    import objaverse
    lvis = objaverse.load_lvis_annotations()
    cat_of = {u: c for c in cats for u in lvis.get(c, [])}
    ann = objaverse.load_annotations(list(cat_of))
    picked: dict[str, list] = {}
    for uid, a in ann.items():
        cat, lic = cat_of[uid], (a.get("license") or "").lower()
        name = a.get("name") or ""
        text = " ".join([name, a.get("description") or ""] + [t["name"] for t in a.get("tags", [])])
        faces = a.get("faceCount") or 0
        if lic not in OK_LICENSES or faces > MAX_FACES or faces < 300 or TRADEMARKS.search(text) or SCENES.search(name):
            continue
        if cats is PLUSH:
            if cat in ANIMALS and not PLUSH_WORDS.search(text):          # a realistic cat isn't a plushie
                continue
            if cat == "toy" and not re.search(r"plush|stuffed|teddy|soft|cute|kawaii|bear|bunny|duck|cat|dog", text, re.I):
                continue
        thumbs = sorted((a.get("thumbnails") or {}).get("images", []), key=lambda t: -t.get("width", 0))
        thumb = next((t["url"] for t in thumbs if t.get("width", 0) <= 1024), thumbs[0]["url"] if thumbs else None)
        if not thumb:
            continue
        quality = (a.get("likeCount") or 0) + 0.02 * (a.get("viewCount") or 0) + \
            (15 if re.search(r"pbr|realistic|photogrammetry|scan|high ?poly|detailed", text, re.I) else 0) - \
            (10 if re.search(r"low ?poly|lowpoly|cartoon|stylized|toon|voxel|pixel", text, re.I) and cats is FURNITURE else 0)
        picked.setdefault(cat, []).append({"uid": uid, "cat": cat, "a": a, "lic": lic, "thumb": thumb, "q": quality})
    # caption checks before downloading anything (the Cap3D file is one local CSV scan)
    caps = captions({r["uid"] for rows in picked.values() for r in rows})
    out = []
    for cat, rows in picked.items():
        keep = []
        for r in sorted(rows, key=lambda r: -r["q"]):
            cap = caps.get(r["uid"], "")
            r["caption"] = cap or None
            if cats is FURNITURE:
                if not cap or not re.search(CAPTION_CONFIRMS[cats[cat][0]], cap, re.I):
                    continue
                if UNSELLABLE.search(f"{r['a'].get('name') or ''} {cap}"):
                    continue
            keep.append(r)
        out += keep[: int((per_category or len(keep)) * 1.5) + 1]   # spares for download/convert/proportion failures
    out.sort(key=lambda r: -r["q"])
    return out[: limit * 2] if limit else out


def fit_size(cat_dims, model_xyz) -> tuple[tuple[float, float, float], float] | None:
    """Scale the model (x=width, y=height, z=depth) so its largest side matches the category's typical largest
    side. Returns ((w, d, h) cm, scale) or None if the proportions are implausible for the category."""
    tw, td, th = cat_dims
    x, y, z = model_xyz
    if min(x, y, z) < 0 or max(x, y, z) <= 0:
        return None
    s = max(tw, td, th) / 100 / max(x, y, z)
    w, h, d = x * s * 100, y * s * 100, z * s * 100
    # allow a model lying sideways (w <-> d), but every side must be within 3x of typical (or tiny for flat things)
    for got, want in ((max(w, d), max(tw, td)), (h, th)):
        if want >= 5 and not (want / 3 <= got <= want * 3):
            return None
    return (round(w, 1), round(d, 1), round(h, 1)), s


def to_product(c: dict, cats: dict, dims, scale: float, hf_path: str, caption: str | None, now: str) -> dict:
    a = c["a"]
    ptype, _, noun = cats[c["cat"]]
    author = (a.get("user") or {}).get("displayName") or "unknown"
    tags = [t["name"] for t in a.get("tags", [])][:15]
    name = (a.get("name") or noun).strip()
    title = name if re.search(rf"\b{re.escape(noun.split()[-1])}", name, re.I) else f"{name} {noun}"
    desc = " ".join(x for x in [caption, (a.get("description") or "").strip()[:1200]] if x) or f"A {noun}."
    plush = cats is PLUSH
    return {
        "id": f"objaverse:{c['uid']}", "source": "objaverse", "source_id": c["uid"], "url": a.get("viewerUrl"),
        "title": title[:200], "brand": None, "product_type": ptype,
        "category": ["Home", "Decor", "Plush Toys"] if plush else ["Home", "Furniture", noun.title()],
        "style": "Cute" if plush else None, "material": "Plush fabric" if plush and ptype == "PLUSH_TOY" else None,
        "color": None, "price": None, "currency": None, "description": desc,
        "keywords": sorted({noun, c["cat"].replace("_", " "), *tags} | ({"cute"} if plush else set())),
        "image_urls": [c["thumb"]], "model_3d_url": HF_BASE + hf_path,
        "width_cm": dims[0], "depth_cm": dims[1], "height_cm": dims[2],
        "caption": caption, "vibe_tags": None,
        "license": f"{OK_LICENSES[c['lic']]}, by {author} on Sketchfab (via Objaverse)",
        "scraped_at": now, "_scale": scale,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", choices=["furniture", "plush"], default="furniture")
    ap.add_argument("--per-category", type=int, default=12, help="furniture: max products per category")
    ap.add_argument("--limit", type=int, default=None, help="overall cap")
    ap.add_argument("--max-mb", type=float, default=25, help="skip original models bigger than this")
    ap.add_argument("--replace", action="store_true",
                    help="remove earlier Objaverse products of this set that this run didn't keep")
    args = ap.parse_args(argv)
    import objaverse

    cats = FURNITURE if args.set == "furniture" else PLUSH
    per_cat = args.per_category if args.set == "furniture" else None
    limit = args.limit or (None if args.set == "furniture" else 40)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    picked = candidates(cats, per_cat, limit)
    print(f"{len(picked)} candidates across {len({c['cat'] for c in picked})} categories; downloading ...")
    paths = objaverse.load_objects([c["uid"] for c in picked], download_processes=6)
    hf_paths = objaverse._load_object_paths()

    skipped = {"too big": 0, "convert": 0, "proportions": 0}

    def prepare(c):
        """Compress + measure one model. Returns a product dict, or the skip reason."""
        raw = Path(paths.get(c["uid"], ""))
        if not raw.is_file() or raw.stat().st_size > args.max_mb * 1e6:
            return "too big"
        out = MODELS_DIR / f"objaverse-{c['uid']}.glb"
        try:
            if not out.exists():
                glb_tools.optimize_glb(raw, out)
            size = glb_tools.glb_bbox(out)
        except Exception:
            out.unlink(missing_ok=True)
            return "convert"
        fit = fit_size(cats[c["cat"]][1], size)
        if not fit:
            return "proportions"
        dims, scale = fit
        return to_product(c, cats, dims, scale, hf_paths[c["uid"]], c.get("caption"), now)

    def run_category(rows):
        """Best-first within a category until it has per_cat products (each model takes ~15 s to compress)."""
        kept, why = [], []
        for c in rows:
            if per_cat and len(kept) >= per_cat:
                break
            r = prepare(c)
            (kept if isinstance(r, dict) else why).append(r)
        return kept, why

    by_cat: dict[str, list] = {}
    for c in picked:
        by_cat.setdefault(c["cat"], []).append(c)
    from concurrent.futures import ThreadPoolExecutor
    products, per_count = [], {}
    with ThreadPoolExecutor(8) as pool:          # categories in parallel; npx/gltf-transform is the slow part
        for kept, why in pool.map(run_category, by_cat.values()):
            for reason in why:
                skipped[reason] += 1
            for p in kept:
                per_count[p["category"][-1]] = per_count.get(p["category"][-1], 0) + 1
            products += kept
    if limit:
        products = products[:limit]

    print(f"kept {len(products)}; skipped {skipped}")
    print("per category:", dict(sorted(per_count.items(), key=lambda kv: -kv[1])))
    conn = psycopg2.connect(database_url(), connect_timeout=20)   # connect late: downloads take minutes
    try:
        with conn, conn.cursor() as cur:
            upsert_products(cur, products)
            cur.executemany(
                "update products set ar_model_url = %s, dims_estimated = true, model_scale = %s where id = %s",
                [(f"/models/objaverse-{p['source_id']}.glb", p["_scale"], p["id"]) for p in products])
            n = upsert_embeddings(cur, products)
            if args.replace:
                types = sorted({v[0] for v in cats.values()})
                cur.execute("delete from products where source = 'objaverse' and product_type = any(%s) "
                            "and not (id = any(%s))", (types, [p["id"] for p in products]))
                print(f"removed {cur.rowcount} earlier {args.set} items that didn't pass this run")
    finally:
        conn.close()
    print(f"imported {len(products)} {args.set} items; embedded {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
