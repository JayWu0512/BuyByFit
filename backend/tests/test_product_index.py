"""Offline tests for the vibe document and indexing helpers (no DB, no model download)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.product import embed  # noqa: E402
from app.services.product import index_products  # noqa: E402

SOFA = {
    "id": "abo:B075X4QMX3", "title": "Rivet Revolve Modern Upholstered Sofa", "product_type": "SOFA",
    "style": "Mid-Century Modern", "material": "Wood", "color": "Grey", "keywords": ["sofa", "couch"],
    "description": "Tapered legs. " + "x" * 2000, "caption": None, "vibe_tags": None,
}


def test_vibe_document_includes_facets_and_skips_empty():
    doc = embed.vibe_document(SOFA)
    assert doc.startswith("Rivet Revolve Modern Upholstered Sofa")
    assert "Type: sofa." in doc and "Style: Mid-Century Modern." in doc and "Color: Grey." in doc
    assert "Vibe:" not in doc  # no tags yet -> no empty facet
    assert len(doc) < 900      # description is truncated


def test_vibe_document_uses_enrichment_when_present():
    doc = embed.vibe_document({**SOFA, "caption": "A low grey sofa.", "vibe_tags": ["mid-century", "cozy"]})
    assert "A low grey sofa." in doc and "Vibe: mid-century, cozy." in doc


def test_to_vector_literal():
    assert index_products.to_vector([0.1, -0.25]) == "[0.100000,-0.250000]"


class _FakeCursor:
    def __init__(self):
        self.sql = []

    def mogrify(self, template, args):  # used by execute_values
        return b"(...)"

    def execute(self, sql, *a):
        self.sql.append(sql if isinstance(sql, str) else sql.decode())

    connection = type("C", (), {"encoding": "UTF8"})()


def test_reimport_keeps_captions_and_vibe_tags():
    cur = _FakeCursor()
    index_products.upsert_products(cur, [SOFA])
    sql = " ".join(cur.sql)
    assert "caption = coalesce(excluded.caption, products.caption)" in sql
    assert "vibe_tags = coalesce(excluded.vibe_tags, products.vibe_tags)" in sql
    assert "title = excluded.title" in sql          # normal columns still update


def test_schema_dims_match_model():
    sql = index_products.SCHEMA_SQL.read_text()
    assert f"vector({embed.EMBEDDING_DIM})" in sql
    assert embed.EMBEDDING_MODEL in sql and embed.EMBEDDING_VERSION in sql
