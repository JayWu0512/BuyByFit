"""Objaverse import rules: sizing from typical dims, and the caption/sellability filters (no network)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.product.objaverse_import import (  # noqa: E402
    CAPTION_CONFIRMS, FURNITURE, SCENES, TRADEMARKS, UNSELLABLE, fit_size,
)


def test_fit_size_scales_to_typical_and_keeps_proportions():
    # a sofa modelled 2 units wide, 0.9 deep, 0.85 tall (arbitrary units) -> 200 cm wide
    (w, d, h), s = fit_size(FURNITURE["sofa"][1], (2.0, 0.85, 0.9))
    assert (w, d, h) == (200.0, 90.0, 85.0) and s == 1.0
    # same shape modelled in centimetres (x100) -> same result, scale 0.01
    (w2, d2, h2), s2 = fit_size(FURNITURE["sofa"][1], (200.0, 85.0, 90.0))
    assert (w2, d2, h2) == (200.0, 90.0, 85.0) and abs(s2 - 0.01) < 1e-9


def test_fit_size_rejects_implausible_proportions():
    # a "chair" that is a flat 2 x 2 plate isn't a chair
    assert fit_size(FURNITURE["chair"][1], (1.0, 0.01, 1.0)) is None
    # a "bookcase" lying on its side is fine (width/depth swap is allowed, height must be plausible)
    assert fit_size(FURNITURE["bookcase"][1], (0.9, 1.8, 0.35)) is not None


def test_caption_must_confirm_category():
    assert re.search(CAPTION_CONFIRMS["HOME_MIRROR"], "An oval wall mirror with a gold frame.", re.I)
    assert not re.search(CAPTION_CONFIRMS["HOME_MIRROR"], "White oval-shaped wall light.", re.I)
    assert re.search(CAPTION_CONFIRMS["SOFA"], "A grey three-seat couch with wooden legs.", re.I)


def test_unsellable_scenes_and_trademarks_are_filtered():
    assert UNSELLABLE.search("A rusty metal-framed bed with a stained, worn mattress.")
    assert UNSELLABLE.search("A wicker basket filled with bread and potatoes.")
    assert not UNSELLABLE.search("A worn brown leather armchair with tufted cushioning.")
    assert SCENES.search("Cozy Living Room Scene") and not SCENES.search("Velvet Armchair")
    assert TRADEMARKS.search("Eames Lounge Chair replica")
