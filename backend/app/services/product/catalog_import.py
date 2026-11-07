"""Idempotent importer for the product and embedding CSV exports.

The CSV files are intentionally kept in ``infra/`` and excluded from Git. This
module owns only the repeatable database schema and import mechanics; product
source data remains the CSV export owned by the ingestion workflow.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

PRODUCT_BATCH_SIZE = 500
EMBEDDING_BATCH_SIZE = 100
EMBEDDING_DIMENSIONS = 384

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    brand TEXT,
    product_type TEXT,
    category TEXT[],
    style TEXT,
    material TEXT,
    color TEXT,
    price NUMERIC,
    currency TEXT,
    description TEXT,
    keywords TEXT[],
    image_urls TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    model_3d_url TEXT,
    ar_model_url TEXT,
    width_cm NUMERIC,
    depth_cm NUMERIC,
    height_cm NUMERIC,
    caption TEXT,
    vibe_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    license TEXT,
    scraped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS product_embeddings (
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    vibe_document TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ,
    PRIMARY KEY (product_id, embedding_model, embedding_version)
);

CREATE INDEX IF NOT EXISTS product_embeddings_model_version_idx
    ON product_embeddings (embedding_model, embedding_version);
"""

_PRODUCT_UPSERT = text(
    """
    INSERT INTO products (
        id, source, source_id, url, title, brand, product_type, category,
        style, material, color, price, currency, description, keywords,
        image_urls, model_3d_url, ar_model_url, width_cm, depth_cm, height_cm,
        caption, vibe_tags, license, scraped_at, updated_at
    ) VALUES (
        :id, :source, :source_id, :url, :title, :brand, :product_type, :category,
        :style, :material, :color, :price, :currency, :description, :keywords,
        :image_urls, :model_3d_url, :ar_model_url, :width_cm, :depth_cm, :height_cm,
        :caption, :vibe_tags, :license, :scraped_at, :updated_at
    )
    ON CONFLICT (id) DO UPDATE SET
        source = EXCLUDED.source,
        source_id = EXCLUDED.source_id,
        url = EXCLUDED.url,
        title = EXCLUDED.title,
        brand = EXCLUDED.brand,
        product_type = EXCLUDED.product_type,
        category = EXCLUDED.category,
        style = EXCLUDED.style,
        material = EXCLUDED.material,
        color = EXCLUDED.color,
        price = EXCLUDED.price,
        currency = EXCLUDED.currency,
        description = EXCLUDED.description,
        keywords = EXCLUDED.keywords,
        image_urls = EXCLUDED.image_urls,
        model_3d_url = EXCLUDED.model_3d_url,
        ar_model_url = EXCLUDED.ar_model_url,
        width_cm = EXCLUDED.width_cm,
        depth_cm = EXCLUDED.depth_cm,
        height_cm = EXCLUDED.height_cm,
        caption = EXCLUDED.caption,
        vibe_tags = EXCLUDED.vibe_tags,
        license = EXCLUDED.license,
        scraped_at = EXCLUDED.scraped_at,
        updated_at = EXCLUDED.updated_at
    """
)

_EMBEDDING_UPSERT = text(
    """
    INSERT INTO product_embeddings (
        product_id, embedding_model, embedding_version, vibe_document, embedding, created_at
    ) VALUES (
        :product_id, :embedding_model, :embedding_version, :vibe_document, CAST(:embedding AS vector), :created_at
    )
    ON CONFLICT (product_id, embedding_model, embedding_version) DO UPDATE SET
        vibe_document = EXCLUDED.vibe_document,
        embedding = EXCLUDED.embedding,
        created_at = EXCLUDED.created_at
    """
)


@dataclass(frozen=True)
class ImportSummary:
    products: int
    embeddings: int


def create_catalog_engine(database_url: str) -> Engine:
    """Create the database connection used by the one-off import command."""
    return create_engine(database_url, pool_pre_ping=True)


def ensure_schema(engine: Engine) -> None:
    """Create the pgvector-backed catalogue schema if it does not already exist."""
    with engine.begin() as connection:
        connection.execute(text(_SCHEMA_SQL))


def _as_optional_number(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _as_text_array(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    normalized = value.strip()
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        # The export mixes JSON lists (categories, image URLs) with legacy
        # single-value style labels such as "Modern". Preserve both shapes as
        # JSON arrays instead of rejecting an otherwise usable product row.
        parsed = normalized
    values = parsed if isinstance(parsed, list) else [parsed]
    return [str(item).strip() for item in values if str(item).strip()]


def _as_optional_style(value: str | None) -> str | None:
    values = _as_text_array(value)
    return ", ".join(values) if values else None


def _as_optional_text(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _product_params(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "url": _as_optional_text(row.get("url")),
        "title": row["title"],
        "brand": _as_optional_text(row.get("brand")),
        "product_type": _as_optional_text(row.get("product_type")),
        "category": _as_text_array(row.get("category")),
        "style": _as_optional_style(row.get("style")),
        "material": _as_optional_text(row.get("material")),
        "color": _as_optional_text(row.get("color")),
        "price": _as_optional_number(row.get("price")),
        "currency": _as_optional_text(row.get("currency")),
        "description": _as_optional_text(row.get("description")),
        "keywords": _as_text_array(row.get("keywords")),
        "image_urls": _as_text_array(row.get("image_urls")),
        "model_3d_url": _as_optional_text(row.get("model_3d_url")),
        "ar_model_url": _as_optional_text(row.get("ar_model_url")),
        "width_cm": _as_optional_number(row.get("width_cm")),
        "depth_cm": _as_optional_number(row.get("depth_cm")),
        "height_cm": _as_optional_number(row.get("height_cm")),
        "caption": _as_optional_text(row.get("caption")),
        "vibe_tags": _as_text_array(row.get("vibe_tags")),
        "license": _as_optional_text(row.get("license")),
        "scraped_at": _as_optional_text(row.get("scraped_at")),
        "updated_at": _as_optional_text(row.get("updated_at")),
    }


def _embedding_params(row: dict[str, str]) -> dict[str, Any]:
    embedding = row["embedding"].strip()
    if not embedding.startswith("[") or not embedding.endswith("]"):
        raise ValueError(f"Invalid vector literal for product {row['product_id']}")
    return {
        "product_id": row["product_id"],
        "embedding_model": row["embedding_model"],
        "embedding_version": row["embedding_version"],
        "vibe_document": row["vibe_document"],
        "embedding": embedding,
        "created_at": _as_optional_text(row.get("created_at")),
    }


def _batches(rows: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _read_products(csv_path: Path) -> Iterator[dict[str, Any]]:
    with csv_path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            yield _product_params(row)


def _read_embeddings(csv_path: Path) -> Iterator[dict[str, Any]]:
    with csv_path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            yield _embedding_params(row)


def import_catalog(engine: Engine, products_csv: Path, embeddings_csv: Path) -> ImportSummary:
    """Upsert the exported product records and their precomputed embeddings."""
    product_count = 0
    for batch in _batches(_read_products(products_csv), PRODUCT_BATCH_SIZE):
        with engine.begin() as connection:
            connection.execute(_PRODUCT_UPSERT, batch)
        product_count += len(batch)

    embedding_count = 0
    for batch in _batches(_read_embeddings(embeddings_csv), EMBEDDING_BATCH_SIZE):
        with engine.begin() as connection:
            connection.execute(_EMBEDDING_UPSERT, batch)
        embedding_count += len(batch)

    return ImportSummary(products=product_count, embeddings=embedding_count)
