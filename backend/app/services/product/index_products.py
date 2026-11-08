"""Load normalized products (products.json from abo_import.py) into Supabase Postgres + pgvector.

Usage (from backend/):
    python -m app.services.product.index_products --init --json ~/buybyfit-data/abo/products.json
    python -m app.services.product.index_products --json ...            # re-run: upserts, embeds only new/changed
    python -m app.services.product.index_products --search "cozy warm mid-century living room" --max-w 230 --max-d 100

Reads RELATIONAL_DATABASE_URL from the environment or backend/.env. Never prints it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from app.services.product import embed

BACKEND_DIR = Path(__file__).resolve().parents[3]
SCHEMA_SQL = Path(__file__).with_name("schema.sql")

PRODUCT_COLUMNS = [
    "id", "source", "source_id", "url", "title", "brand", "product_type", "category", "style",
    "material", "color", "price", "currency", "description", "keywords", "image_urls",
    "model_3d_url", "width_cm", "depth_cm", "height_cm", "caption", "vibe_tags", "license", "scraped_at",
]


def database_url() -> str:
    url = os.environ.get("RELATIONAL_DATABASE_URL")
    env_file = BACKEND_DIR / ".env"
    if not url and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("RELATIONAL_DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    if not url:
        sys.exit("RELATIONAL_DATABASE_URL is not set (env or backend/.env)")
    return url


def to_vector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def upsert_products(cur, products: list[dict]) -> None:
    rows = [tuple(p.get(c) for c in PRODUCT_COLUMNS) for p in products]
    # Enrichment columns are filled by later steps (abo_captions.py, vibe_tags.py). A re-import doesn't know
    # them and passes NULL, so keep what's there instead of wiping it.
    keep = {"caption", "vibe_tags"}
    updates = ", ".join(f"{c} = coalesce(excluded.{c}, products.{c})" if c in keep else f"{c} = excluded.{c}"
                        for c in PRODUCT_COLUMNS if c != "id")
    execute_values(
        cur,
        f"insert into products ({', '.join(PRODUCT_COLUMNS)}) values %s "
        f"on conflict (id) do update set {updates}, updated_at = now()",
        rows, page_size=500,
    )


def upsert_embeddings(cur, products: list[dict]) -> int:
    """Embed products whose vibe document is new or changed. Returns how many were embedded."""
    cur.execute(
        "select product_id, vibe_document from product_embeddings where embedding_model = %s and embedding_version = %s",
        (embed.EMBEDDING_MODEL, embed.EMBEDDING_VERSION),
    )
    existing = dict(cur.fetchall())
    # an import file doesn't carry enrichment (Cap3D caption, CLIP vibe tags); take it from the DB so a
    # re-import doesn't re-embed products without their style
    ids = [p["id"] for p in products if not p.get("caption") or not p.get("vibe_tags")]
    if ids:
        cur.execute("select id, caption, vibe_tags from products where id = any(%s)", (ids,))
        enrich = {pid: (cap, tags) for pid, cap, tags in cur.fetchall()}
        products = [{**p, "caption": p.get("caption") or enrich.get(p["id"], (None, None))[0],
                     "vibe_tags": p.get("vibe_tags") or enrich.get(p["id"], (None, None))[1]} for p in products]
    todo = [(p["id"], embed.vibe_document(p)) for p in products]
    todo = [(pid, doc) for pid, doc in todo if existing.get(pid) != doc]
    if not todo:
        return 0
    vectors = embed.embed_documents([doc for _, doc in todo])
    rows = [(pid, embed.EMBEDDING_MODEL, embed.EMBEDDING_VERSION, doc, to_vector(v))
            for (pid, doc), v in zip(todo, vectors)]
    execute_values(
        cur,
        "insert into product_embeddings (product_id, embedding_model, embedding_version, vibe_document, embedding) "
        "values %s on conflict (product_id, embedding_model, embedding_version) do update set "
        "vibe_document = excluded.vibe_document, embedding = excluded.embedding, created_at = now()",
        rows, template="(%s, %s, %s, %s, %s::vector)", page_size=200,
    )
    return len(rows)


def search(cur, query: str, max_w=None, max_d=None, max_h=None, types=None, k=10, require_ar=False) -> list[dict]:
    cur.execute(
        "select * from match_products(%s::vector, %s, %s, %s, %s::text[], %s, %s, %s, %s)",
        (to_vector(embed.embed_query(query)), max_w, max_d, max_h, types, k,
         embed.EMBEDDING_MODEL, embed.EMBEDDING_VERSION, require_ar),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", type=Path, help="products.json from abo_import.py")
    ap.add_argument("--init", action="store_true", help="apply schema.sql (safe to re-run)")
    ap.add_argument("--search", help="run a vibe search instead of indexing")
    ap.add_argument("--max-w", type=float)
    ap.add_argument("--max-d", type=float)
    ap.add_argument("--max-h", type=float)
    ap.add_argument("--types", help="comma-separated product_type filter, e.g. SOFA,CHAIR")
    ap.add_argument("-k", type=int, default=10)
    args = ap.parse_args(argv)

    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            if args.init:
                cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
                print("schema applied")
            if args.json:
                products = json.loads(args.json.read_text(encoding="utf-8"))
                upsert_products(cur, products)
                print(f"upserted {len(products)} products")
                n = upsert_embeddings(cur, products)
                print(f"embedded {n} products ({embed.EMBEDDING_MODEL}, {embed.EMBEDDING_VERSION})")
            if args.search:
                types = args.types.split(",") if args.types else None
                for i, r in enumerate(search(cur, args.search, args.max_w, args.max_d, args.max_h, types, args.k), 1):
                    print(f"{i:2}. {r['similarity']:.3f}  {r['product_type']:<14} "
                          f"{r['width_cm']:.0f}x{r['depth_cm']:.0f}x{r['height_cm']:.0f}cm  "
                          f"{'3D ' if r['model_3d_url'] else '   '}{r['title'][:70]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
