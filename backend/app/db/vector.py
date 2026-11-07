"""Cosine-similarity search against `product_embeddings`.

Store/retrieve vectors only; product metadata stays authoritative in the
relational tables. Reads from the same Postgres database (pgvector) that
`relational.py` will eventually own the connection for -- this module opens
its own engine for now since that file isn't implemented yet.

`EMBEDDING_MODEL_NAME`/`EMBEDDING_VERSION` must match the values Diwas's
ingestion pipeline writes into `product_embeddings`; a mismatch returns zero
rows rather than an error.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.services.logic.embeddings import EMBEDDING_MODEL_NAME

load_dotenv()

EMBEDDING_VERSION = "text-v1"  # confirm with Diwas when the pipeline stabilizes

_engine: Engine | None = None

_SIMILARITY_QUERY = text(
    """
    SELECT
        p.id,
        p.title,
        p.brand,
        p.product_type,
        p.category,
        p.price,
        p.currency,
        p.url,
        p.image_urls,
        p.model_3d_url,
        p.ar_model_url,
        p.width_cm,
        p.depth_cm,
        p.height_cm,
        p.description,
        p.material,
        p.color,
        p.style,
        p.vibe_tags,
        p.caption,
        pe.embedding <=> (:query_vector)::vector AS distance
    FROM products p
    JOIN product_embeddings pe ON pe.product_id = p.id
    WHERE pe.embedding_model = :embedding_model
      AND pe.embedding_version = :embedding_version
    ORDER BY distance
    LIMIT :limit
    """
)


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["RELATIONAL_DATABASE_URL"])
    return _engine


def similarity_search(query_vector: list[float], *, limit: int = 50) -> list[dict]:
    """Return up to `limit` products nearest to `query_vector`, closest first."""
    vector_literal = "[" + ",".join(str(value) for value in query_vector) + "]"
    with _get_engine().connect() as conn:
        rows = conn.execute(
            _SIMILARITY_QUERY,
            {
                "query_vector": vector_literal,
                "embedding_model": EMBEDDING_MODEL_NAME,
                "embedding_version": EMBEDDING_VERSION,
                "limit": limit,
            },
        ).mappings().all()
    return [dict(row) for row in rows]
