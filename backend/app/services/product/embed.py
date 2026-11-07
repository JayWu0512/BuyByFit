"""Vibe document builder + text embeddings for products.

The vibe document is the one string per product that the text vector represents.
The user's spoken query is embedded with the same model (see `embed_query`).
Bump EMBEDDING_VERSION whenever `vibe_document` changes, so old and new vectors never mix.
"""
from __future__ import annotations

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"   # 384-dim, local, free
EMBEDDING_VERSION = "text-v1"
EMBEDDING_DIM = 384
# bge models want this prefix on queries (not on documents)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_MAX_DESC_CHARS = 600
_model = None


def vibe_document(p: dict) -> str:
    """Build the text that describes how a product looks and feels."""
    parts = [p.get("title") or ""]
    if p.get("caption"):
        parts.append(p["caption"])
    facets = [
        ("Type", (p.get("product_type") or "").replace("_", " ").lower()),
        ("Style", p.get("style")),
        ("Vibe", ", ".join(p.get("vibe_tags") or [])),
        ("Material", p.get("material")),
        ("Color", p.get("color")),
    ]
    parts += [f"{k}: {v}." for k, v in facets if v]
    if p.get("keywords"):
        parts.append("Keywords: " + ", ".join(p["keywords"][:12]) + ".")
    if p.get("description"):
        parts.append(p["description"][:_MAX_DESC_CHARS])
    return " ".join(s.strip() for s in parts if s and s.strip())


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed_documents(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    vecs = _get_model().encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=True)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    return _get_model().encode(QUERY_PREFIX + text, normalize_embeddings=True).tolist()
