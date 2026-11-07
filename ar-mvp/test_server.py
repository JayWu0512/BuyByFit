"""Voice-text parser tests (no DB, no model).  Run: python -m pytest ar-mvp"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import parse_query, split_items  # noqa: E402


def fit(q):
    return q["max_w"], q["max_d"], q["max_h"]


def test_cm_by_cm_and_type():
    q = parse_query("a cozy mid-century sofa that fits 230 by 100")
    assert fit(q) == (230.0, 100.0, None) and q["types"] == ["SOFA"]
    assert q["vibe"] == "a cozy mid-century sofa"


def test_metres_spelled_out():
    q = parse_query("something airy and scandinavian for 2 by 1 meters")
    assert fit(q) == (200.0, 100.0, None)
    assert "eters" not in q["vibe"]


def test_small_numbers_without_unit_are_metres():
    assert fit(parse_query("2.2 x 0.9"))[:2] == (220.0, 90.0)


def test_feet_and_three_dims():
    assert fit(parse_query("a velvet armchair 7 ft x 3 ft x 3 ft")) == (213.4, 91.4, 91.4)


def test_single_axis_words():
    q = parse_query("dark industrial desk under 140 cm wide and 75 cm deep")
    assert (q["max_w"], q["max_d"]) == (140.0, 75.0) and q["types"] == ["DESK"]


def test_inches_and_word_boundaries():
    q = parse_query("a mid century coffee table 48 inches wide made of walnut")
    assert q["max_w"] == 121.9 and q["types"] == ["TABLE"]
    assert "made" in q["vibe"]


def test_cute_types():
    assert parse_query("a fluffy teddy bear")["types"] == ["PLUSH_TOY"]
    assert parse_query("cute bunny plushie")["types"] == ["PLUSH_TOY"]
    assert parse_query("a cozy bean bag chair")["types"] == ["BEAN_BAG_CHAIR"]
    assert parse_query("a ceramic planter")["types"][0] == "PLANTER"
    assert parse_query("a brass floor lamp")["types"] == ["LAMP"]


def test_split_items_multi_and_keeps_compound_colours():
    assert split_items("a cozy mid-century sofa, a brass floor lamp and a teddy bear") == [
        "a cozy mid-century sofa", "a brass floor lamp", "a teddy bear"]
    assert split_items("a black and white rug") == ["a black and white rug"]
    assert split_items("show me a velvet sofa with a round coffee table") == ["a velvet sofa", "a round coffee table"]
    assert split_items("something cozy") == ["something cozy"]


def test_armchair_is_chair_and_no_dims():
    q = parse_query("boho rattan armchair")
    assert q["types"] == ["CHAIR"] and fit(q) == (None, None, None)
