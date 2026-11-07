"""Pick a demo set of products with 3D models, compress them for phones, and mark them AR-ready.

    python ar-mvp/prepare_models.py            # ~45 items, skips originals > 20 MB
    python ar-mvp/prepare_models.py --per-type 2 --max-mb 10

For each product: download the ABO .glb -> gltf-transform optimize (1K textures, Draco)
-> ar-mvp/models/<source_id>.glb -> products.ar_model_url = '/models/<source_id>.glb'.
Re-running skips models already compressed. Needs Node (npx) for @gltf-transform/cli.
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.product import glb_tools  # noqa: E402
from app.services.product.index_products import database_url  # noqa: E402

import psycopg2  # noqa: E402

MODELS_DIR = Path(__file__).resolve().parent / "models"
RAW_DIR = Path.home() / "buybyfit-data" / "glb-raw"

QUOTA = {  # product_type -> how many to pick (scaled by --per-type)
    "SOFA": 8, "CHAIR": 8, "TABLE": 5, "HOME_FURNITURE_AND_DECOR": 4, "OTTOMAN": 3, "LAMP": 3,
    "RUG": 2, "STOOL_SEATING": 2, "SHELF": 2, "CABINET": 2, "DRESSER": 2, "DESK": 2, "BED": 2, "BENCH": 2,
    # small cute decor (plushies come from objaverse_import.py)
    "PILLOW": 6, "PLANTER": 6, "VASE": 4, "BEAN_BAG_CHAIR": 3, "CANDLE_HOLDER": 2, "FIGURINE": 1,
    "SCULPTURE": 1, "ARTIFICIAL_PLANT": 1, "BASKET": 2, "CLOCK": 1, "LIGHT_FIXTURE": 2,
}


def head_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("Content-Length", 0))


def pick(cur, scale: float, max_bytes: int) -> list[tuple[str, str, str]]:
    cur.execute(
        "select id, source_id, model_3d_url, product_type, title from products "
        "where model_3d_url is not null and product_type = any(%s) "
        # floor plants and vases read better tall: pick the tallest first for those types
        "order by product_type, case when product_type in ('PLANTER', 'VASE', 'ARTIFICIAL_PLANT') "
        "then -coalesce(height_cm, 0) else 0 end, id",
        (list(QUOTA),),
    )
    by_type: dict[str, list] = {}
    for row in cur.fetchall():
        by_type.setdefault(row[3], []).append(row)
    chosen = []
    for t, quota in QUOTA.items():
        want, seen_titles = max(1, round(quota * scale)), set()
        for pid, sid, url, _, title in by_type.get(t, []):
            if len([c for c in chosen if c[3] == t]) >= want:
                break
            key = title.lower()[:45]  # skip colour variants of the same item
            if key in seen_titles:
                continue
            if not (MODELS_DIR / f"{sid}.glb").exists():
                try:
                    if head_size(url) > max_bytes:
                        continue
                except OSError:
                    continue
            seen_titles.add(key)
            chosen.append((pid, sid, url, t))
    return [(pid, sid, url) for pid, sid, url, _ in chosen]


def prepare(item: tuple[str, str, str]) -> tuple[str, str | None]:
    pid, sid, url = item
    out = MODELS_DIR / f"{sid}.glb"
    if out.exists():
        return pid, f"/models/{sid}.glb"
    raw = RAW_DIR / f"{sid}.glb"
    try:
        if not raw.exists():
            urllib.request.urlretrieve(url, raw)
        glb_tools.optimize_glb(raw, out)
        return pid, f"/models/{sid}.glb"
    except Exception as e:  # keep going; report at the end
        print(f"  failed {sid}: {type(e).__name__}")
        out.unlink(missing_ok=True)
        return pid, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-type", type=float, default=1.0, help="scale the per-type quota")
    ap.add_argument("--max-mb", type=float, default=20)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    MODELS_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # short-lived connections: downloads take minutes and the Supabase pooler drops idle sessions
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            items = pick(cur, args.per_type, int(args.max_mb * 1e6))
    finally:
        conn.close()
    print(f"preparing {len(items)} models ...")
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(prepare, items))
    ok = [(url, pid) for pid, url in results if url]
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            cur.executemany("update products set ar_model_url = %s where id = %s", ok)
    finally:
        conn.close()
    mb = sum(f.stat().st_size for f in MODELS_DIR.glob("*.glb")) / 1e6
    print(f"AR-ready: {len(ok)}/{len(items)}  ({mb:.0f} MB in {MODELS_DIR})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
