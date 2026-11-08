"""Add Cap3D captions to ABO products and re-embed them.

    python -m app.services.product.abo_captions            (from backend/)

ABO's text is marketing copy ("Amazon Brand - Rivet ... 32.7"W"); Cap3D (tiange/Cap3D, ODC-By) has an
automatic caption of each ABO 3D model that says what the thing looks like ("a low grey three-seat sofa
with tapered wooden legs"). vibe_document() already puts `caption` right after the title, so filling it and
re-running upsert_embeddings re-embeds exactly the products whose document changed (same model/version, so
search keeps working throughout).
"""
from __future__ import annotations

import csv
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url, upsert_embeddings

FIELDS = ["id", "title", "product_type", "style", "material", "color", "keywords", "description", "caption", "vibe_tags"]


def main() -> int:
    from huggingface_hub import hf_hub_download
    path = hf_hub_download("tiange/Cap3D", "Cap3D_automated_ABO.csv", repo_type="dataset")
    caps = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):          # model_id, kind ("general"), caption
            text = (row[2] if len(row) >= 3 else row[1] if len(row) == 2 else "").strip()
            if text:
                caps[row[0].strip()] = text
    print(f"Cap3D ABO captions: {len(caps)}")

    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("select id, model_3d_url from products where source = 'abo' and model_3d_url is not null")
            updates = []
            for pid, url in cur.fetchall():
                model_id = Path(url).stem              # .../3dmodels/original/K/B07DBJQC1K.glb -> B07DBJQC1K
                if model_id in caps:
                    updates.append((pid, caps[model_id]))
            print(f"matched {len(updates)} ABO products to a caption")
            execute_values(cur, "update products p set caption = v.cap from (values %s) as v(id, cap) where p.id = v.id",
                           updates, page_size=1000)
            cur.execute(f"select {', '.join(FIELDS)} from products where source = 'abo'")
            products = [dict(zip(FIELDS, r)) for r in cur.fetchall()]
            n = upsert_embeddings(cur, products)
            print(f"re-embedded {n} ABO products whose vibe document changed")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
