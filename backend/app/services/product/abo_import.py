"""Import furniture from the Amazon Berkeley Objects (ABO) dataset into the BuyByFit product schema.

Data: https://amazon-berkeley-objects.s3.amazonaws.com/index.html  (CC BY 4.0, credit "Amazon.com")
Stdlib only. Downloads ~83 MB of listings plus two small metadata files, then writes JSON + CSV.

Usage:
    python abo_import.py --out data/abo                 # default furniture types
    python abo_import.py --list-types                   # show product_type counts, then exit
    python abo_import.py --types SOFA,CHAIR --require-dims --require-3d --limit 500
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import tarfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://amazon-berkeley-objects.s3.amazonaws.com"
LISTINGS_TAR = f"{BASE}/archives/abo-listings.tar"
IMAGES_META = f"{BASE}/images/metadata/images.csv.gz"
MODELS_META = f"{BASE}/3dmodels/metadata/3dmodels.csv.gz"

DEFAULT_TYPES = {
    "SOFA", "CHAIR", "TABLE", "BED", "BED_FRAME", "DESK", "OTTOMAN", "BENCH", "STOOL_SEATING",
    "SHELF", "BOOKCASE", "CABINET", "DRESSER", "NIGHTSTAND", "STORAGE_BENCH", "HOME_FURNITURE_AND_DECOR",
    "RUG", "LAMP", "MIRROR", "VANITY", "TV_STAND", "COFFEE_TABLE", "END_TABLE", "HEADBOARD", "MATTRESS",
    # small, cute decor (most of these have 3D models in ABO)
    "PILLOW", "PLANTER", "VASE", "BEAN_BAG_CHAIR", "CANDLE_HOLDER", "FIGURINE", "SCULPTURE", "ARTIFICIAL_PLANT",
    "BASKET", "CLOCK", "LIGHT_FIXTURE", "HOME_MIRROR", "WALL_ART",
}

UNIT_TO_CM = {"inches": 2.54, "inch": 2.54, "in": 2.54, "centimeters": 1.0, "centimetres": 1.0, "cm": 1.0,
              "millimeters": 0.1, "mm": 0.1, "feet": 30.48, "ft": 30.48, "meters": 100.0, "m": 100.0}

CSV_COLS = ["id", "source", "source_id", "url", "title", "brand", "product_type", "category", "style",
            "material", "color", "width_cm", "depth_cm", "height_cm", "image_urls", "model_3d_url",
            "description", "scraped_at"]


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def pick_text(entries, prefer=("en_US", "en_GB", "en_CA", "en_AU", "en_IN")) -> str | None:
    """ABO text fields are lists of {language_tag, value}. Prefer English."""
    if not entries:
        return None
    if isinstance(entries, str):
        return entries
    for tag in prefer:
        for e in entries:
            if e.get("language_tag") == tag and e.get("value"):
                return e["value"]
    for e in entries:
        if str(e.get("language_tag", "")).startswith("en") and e.get("value"):
            return e["value"]
    return None  # non-English only: skip


def all_text(entries) -> list[str]:
    vals = []
    for e in entries or []:
        tag = str(e.get("language_tag", "en"))
        if tag.startswith("en") and e.get("value"):
            vals.append(e["value"])
    return vals


MAX_DIM_CM = 600.0


def dim_cm(d) -> float | None:
    if not d:
        return None
    src = d.get("normalized_value") or d
    try:
        v = float(src.get("value"))
    except (TypeError, ValueError):
        return None
    factor = UNIT_TO_CM.get(str(src.get("unit", "")).lower())
    if not factor:
        return None
    cm = round(v * factor, 1)
    # 0 means "not filled in" in ABO, and >6 m is a unit error (e.g. Solimo sofas listed at 845 cm).
    # Treat both as unknown so they can't slip through a room-fit filter.
    if cm <= 0 or cm > MAX_DIM_CM:
        return None
    return cm


def load_listings(listings_tar: Path):
    with tarfile.open(listings_tar) as tar:
        for m in tar.getmembers():
            if re.search(r"listings/metadata/listings_[0-9a-f]+\.json\.gz$", m.name):
                with gzip.open(tar.extractfile(m), "rt", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            yield json.loads(line)


def load_csv_gz(path: Path, key: str, val: str) -> dict[str, str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {row[key]: row[val] for row in csv.DictReader(f)}


def to_product(item: dict, image_paths: dict, model_paths: dict, image_size: str, now: str) -> dict | None:
    title = pick_text(item.get("item_name"))
    if not title:
        return None
    dims = item.get("item_dimensions") or {}
    img_ids = [i for i in [item.get("main_image_id"), *(item.get("other_image_id") or [])] if i]
    images = [f"{BASE}/images/{image_size}/{image_paths[i]}" for i in img_ids if i in image_paths]
    model_id = item.get("3dmodel_id")
    model_url = f"{BASE}/3dmodels/original/{model_paths[model_id]}" if model_id in model_paths else None
    ptype = (item.get("product_type") or [{}])[0].get("value")
    nodes = [n.get("node_name", "").strip("/") for n in item.get("node") or [] if n.get("node_name")]
    bullets = all_text(item.get("bullet_point"))
    desc = pick_text(item.get("product_description")) or " ".join(bullets) or None
    colors = [c.get("standardized_values", [c.get("value")])[0] for c in item.get("color") or []
              if str(c.get("language_tag", "en")).startswith("en")]
    return {
        "id": f"abo:{item['item_id']}",
        "source": "abo",
        "source_id": item["item_id"],
        "url": f"https://www.{item.get('domain_name', 'amazon.com')}/dp/{item['item_id']}",
        "title": title,
        "brand": pick_text(item.get("brand")),
        "product_type": ptype,
        "category": nodes[0].split("/") if nodes else [],
        "style": pick_text(item.get("style")),
        "material": pick_text(item.get("material")),
        "color": next((c for c in colors if c), None),
        "price": None,
        "currency": None,
        "description": desc,
        "image_urls": images,
        "model_3d_url": model_url,
        # ABO: width = side to side, length = front to back (depth), height = vertical
        "width_cm": dim_cm(dims.get("width")),
        "depth_cm": dim_cm(dims.get("length")),
        "height_cm": dim_cm(dims.get("height")),
        "keywords": all_text(item.get("item_keywords"))[:20],
        "caption": None,
        "vibe_tags": None,
        "license": "CC BY 4.0, credit Amazon.com (Amazon Berkeley Objects)",
        "scraped_at": now,
    }


def write_outputs(products: list[dict], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "products.json").write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for p in products:
            w.writerow([" | ".join(p[c]) if isinstance(p.get(c), list) else ("" if p.get(c) is None else p[c])
                        for c in CSV_COLS])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/abo", help="output folder")
    ap.add_argument("--cache", default="data/abo/_cache", help="where downloads are kept")
    ap.add_argument("--types", help="comma-separated product_type values (default: furniture set)")
    ap.add_argument("--list-types", action="store_true", help="print product_type counts and exit")
    ap.add_argument("--require-dims", action="store_true", help="keep only items with width, depth and height")
    ap.add_argument("--require-3d", action="store_true", help="keep only items that have a 3D model")
    ap.add_argument("--image-size", choices=["small", "original"], default="small")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    listings_tar = fetch(LISTINGS_TAR, cache / "abo-listings.tar")

    if args.list_types:
        counts = Counter((i.get("product_type") or [{}])[0].get("value") for i in load_listings(listings_tar))
        for t, n in counts.most_common():
            print(f"{n:7d}  {t}")
        return 0

    types = {t.strip().upper() for t in args.types.split(",")} if args.types else DEFAULT_TYPES
    image_paths = load_csv_gz(fetch(IMAGES_META, cache / "images.csv.gz"), "image_id", "path")
    model_paths = load_csv_gz(fetch(MODELS_META, cache / "3dmodels.csv.gz"), "3dmodel_id", "path")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen, products = set(), []
    for item in load_listings(listings_tar):
        ptype = (item.get("product_type") or [{}])[0].get("value")
        if ptype not in types or item.get("item_id") in seen:
            continue
        p = to_product(item, image_paths, model_paths, args.image_size, now)
        if not p:
            continue
        if args.require_dims and None in (p["width_cm"], p["depth_cm"], p["height_cm"]):
            continue
        if args.require_3d and not p["model_3d_url"]:
            continue
        seen.add(item["item_id"])
        products.append(p)
        if args.limit and len(products) >= args.limit:
            break

    write_outputs(products, Path(args.out))
    with_dims = sum(1 for p in products if p["width_cm"] and p["depth_cm"] and p["height_cm"])
    with_3d = sum(1 for p in products if p["model_3d_url"])
    print(f"wrote {len(products)} products to {args.out} ({with_dims} with full dims, {with_3d} with 3D models)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
