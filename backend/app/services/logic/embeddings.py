"""Embeds the user's style/vibe query text.

Must stay aligned with the product-side embedding model in
``product_embeddings.embedding_model`` (see Diwas's ingestion pipeline) --
mismatched models mean the vectors live in different spaces and cosine
similarity against them is meaningless.
"""

from __future__ import annotations

from fastembed import TextEmbedding

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return _model


def embed_query(text: str) -> list[float]:
    """Embed a single user query string for similarity search against products."""
    vector = next(iter(_get_model().query_embed(text)))
    return vector.tolist()
