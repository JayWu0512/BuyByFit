"""Price estimate model: sane ordering, sets/sectionals/materials, friendly rounding (no DB)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.product.price_estimate import estimate, nice  # noqa: E402


def mid(p):
    lo, hi, _ = estimate(p)
    return (lo + hi) / 2


SOFA = {"product_type": "SOFA", "title": "Rivet Cyprus Mid-Century Sofa", "brand": "Rivet", "material": "Fabric",
        "width_cm": 210, "depth_cm": 90, "height_cm": 80}


def test_range_is_labelled_and_ordered():
    lo, hi, basis = estimate(SOFA)
    assert 400 < lo < hi < 1500
    assert basis.startswith("sofa") and "Rivet" in basis


def test_bigger_leather_and_premium_brand_cost_more():
    assert mid({**SOFA, "width_cm": 280}) > mid(SOFA)
    assert mid({**SOFA, "material": "Top-grain leather"}) > mid(SOFA)
    assert mid({**SOFA, "material": "Faux leather"}) < mid(SOFA)
    assert mid({**SOFA, "title": "Stone & Beam Sofa", "brand": "Stone & Beam"}) > mid(SOFA)
    assert mid({**SOFA, "title": "AmazonBasics Sofa", "brand": "AmazonBasics"}) < mid(SOFA)


def test_sets_and_sectionals():
    stool = {"product_type": "STOOL_SEATING", "title": "Bar Stool", "width_cm": 45, "depth_cm": 45, "height_cm": 75}
    assert mid({**stool, "title": "Bar Stools, Set of 2"}) > 1.7 * mid(stool)
    assert mid({**SOFA, "title": "Rivet Modern L-Sectional"}) > 1.3 * mid(SOFA)


def test_small_decor_is_cheap_and_rugs_scale_by_area():
    plush = estimate({"product_type": "PLUSH_TOY", "title": "Teddy bear", "width_cm": 25, "depth_cm": 20, "height_cm": 35})
    assert plush[1] < 60
    small = {"product_type": "RUG", "title": "Rug", "width_cm": 150, "depth_cm": 90, "height_cm": 1}
    big = {**small, "width_cm": 300, "depth_cm": 240}
    assert mid(big) > 2.5 * mid(small)


def test_nice_rounding():
    assert nice(447) == 450 and nice(1337) == 1325 and nice(87) == 85 and nice(12.4) == 12
