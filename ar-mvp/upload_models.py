"""Publish the compressed AR models (ar-mvp/models/*.glb) to a public Supabase Storage bucket and point
products.ar_model_url at them, so the web app, phones and the AR demo can load them from anywhere.

    python ar-mvp/upload_models.py              # upload what's missing, then update the DB
    python ar-mvp/upload_models.py --dry-run

Needs the project's secret key in backend/.env (never in the frontend):
    SUPABASE_SECRET_KEY=sb_secret_...      (Supabase > Project Settings > API keys)
The bucket is public read-only; only the secret key can write to it.
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
import psycopg2  # noqa: E402

from app.services.product.index_products import database_url  # noqa: E402

BUCKET = "models"
MODELS_DIR = HERE / "models"


def env() -> dict:
    out = {}
    for line in (HERE.parent / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def storage(base: str, key: str, method: str, path: str, data: bytes | None = None, ctype="application/json"):
    req = urllib.request.Request(f"{base}/storage/v1/{path}", data=data, method=method,
                                 headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": ctype,
                                          "Cache-Control": "max-age=31536000", "x-upsert": "true"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    e = env()
    base, key = e["SUPABASE_URL"].rstrip("/"), e.get("SUPABASE_SECRET_KEY", "")
    if not key.startswith("sb_secret"):
        sys.exit("Add SUPABASE_SECRET_KEY=sb_secret_... to backend/.env (Supabase > Project Settings > API keys).")

    conn = psycopg2.connect(database_url(), connect_timeout=20)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("select id, ar_model_url from products where ar_model_url like '/models/%'")
    todo = cur.fetchall()
    print(f"{len(todo)} products still point at the local AR server")
    if args.dry_run or not todo:
        return 0

    import json
    status = storage(base, key, "POST", "bucket", json.dumps(
        {"id": BUCKET, "name": BUCKET, "public": True, "file_size_limit": 15 * 1024 * 1024,
         "allowed_mime_types": ["model/gltf-binary"]}).encode())
    print(f"bucket '{BUCKET}': HTTP {status} (409 = already exists)")

    done = []
    for i, (pid, url) in enumerate(todo, 1):
        f = MODELS_DIR / Path(url).name
        if not f.exists():
            print(f"  missing locally, skipped: {f.name}")
            continue
        s = storage(base, key, "POST", f"object/{BUCKET}/{f.name}", f.read_bytes(), "model/gltf-binary")
        if s in (200, 201):
            done.append((f"{base}/storage/v1/object/public/{BUCKET}/{f.name}", pid))
        else:
            print(f"  upload failed ({s}): {f.name}")
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}")
    cur.executemany("update products set ar_model_url = %s where id = %s", done)
    print(f"pointed {len(done)} products at Supabase Storage")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
