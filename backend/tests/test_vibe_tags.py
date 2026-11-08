"""Relative style tagging: tags go to products that stand out for that style, not to everyone (no model)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.product.vibe_tags import LOOKS, STYLES, pick  # noqa: E402


def test_pick_tags_only_standouts():
    names = ["boho", "industrial", "glam"]
    # 6 products; product 0 is clearly boho, product 1 clearly industrial, the rest are average
    scores = np.array([[0.40, 0.20, 0.21], [0.20, 0.41, 0.20], [0.25, 0.25, 0.25],
                       [0.25, 0.24, 0.25], [0.24, 0.25, 0.25], [0.25, 0.25, 0.24]])
    tags = pick(scores, names, k=2, z_min=0.9)
    assert tags[0] == ["boho"] and tags[1] == ["industrial"]
    assert all(t == [] for t in tags[2:])        # average-looking products get no style tag


def test_vocabulary_is_fixed_and_described():
    assert {"japandi", "boho", "scandinavian", "mid-century", "industrial"} <= set(STYLES)
    assert all(len(d) >= 1 for d in list(STYLES.values()) + list(LOOKS.values()))
