"""Load local CSV product exports into the configured pgvector database.

Run from ``backend/``:
    python scripts/import_catalog.py

The importer is idempotent: rerunning it updates CSV-sourced records instead
of creating duplicates. Use ``--dry-run`` to validate both CSV files without
writing to the database.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import BuyByFit catalogue CSV exports into PostgreSQL/pgvector.")
    parser.add_argument("--products", type=Path, default=REPOSITORY_ROOT / "infra/products_rows.csv")
    parser.add_argument("--embeddings", type=Path, default=REPOSITORY_ROOT / "infra/product_embeddings_rows.csv")
    parser.add_argument("--dry-run", action="store_true", help="Validate input files without writing to the database.")
    return parser.parse_args()


def validate_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{label} CSV not found: {path}")


def main() -> None:
    args = parse_args()
    validate_file(args.products, "Products")
    validate_file(args.embeddings, "Embeddings")

    if args.dry_run:
        with args.products.open(newline="", encoding="utf-8") as products, args.embeddings.open(newline="", encoding="utf-8") as embeddings:
            product_rows = sum(1 for _ in csv.DictReader(products))
            embedding_rows = sum(1 for _ in csv.DictReader(embeddings))
        print(f"Validated {product_rows} products and {embedding_rows} embeddings. No database changes made.")
        return

    from dotenv import load_dotenv

    from app.services.product.catalog_import import create_catalog_engine, ensure_schema, import_catalog

    load_dotenv(BACKEND_DIR / ".env")
    database_url = os.environ.get("RELATIONAL_DATABASE_URL")
    if not database_url:
        raise SystemExit("RELATIONAL_DATABASE_URL must be set in backend/.env or the environment.")

    engine = create_catalog_engine(database_url)
    ensure_schema(engine)
    summary = import_catalog(engine, args.products, args.embeddings)
    print(f"Imported {summary.products} products and {summary.embeddings} embeddings.")


if __name__ == "__main__":
    main()
