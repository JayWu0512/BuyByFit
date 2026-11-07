"""Synthetic-room tests for analyze + planner (no DB, no GPU).  Run: python -m pytest ar-mvp/room"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import analyze  # noqa: E402
from planner import Planner, slots_for  # noqa: E402

W, D, H = 4.5, 3.6, 2.5


def box_surface(rng, x0, x1, y0, y1, z0, z1, n):
    """Points on the 5 visible faces of a box (no bottom)."""
    faces = []
    for _ in range(n):
        f = rng.integers(5)
        u, v = rng.random(2)
        if f == 0: faces.append((x0 + u * (x1 - x0), y1, z0 + v * (z1 - z0)))
        elif f == 1: faces.append((x0, y0 + u * (y1 - y0), z0 + v * (z1 - z0)))
        elif f == 2: faces.append((x1, y0 + u * (y1 - y0), z0 + v * (z1 - z0)))
        elif f == 3: faces.append((x0 + u * (x1 - x0), y0 + v * (y1 - y0), z0))
        else: faces.append((x0 + u * (x1 - x0), y0 + v * (y1 - y0), z1))
    return np.array(faces)


def synthetic_room(with_bed=True, seed=0):
    rng = np.random.default_rng(seed)
    floor = np.c_[rng.random(60000) * W, np.zeros(60000), rng.random(60000) * D]
    walls = []
    for _ in range(40000):
        u, v, side = rng.random(), rng.random() * H, rng.integers(4)
        walls.append([(u * W, v, 0), (u * W, v, D), (0, v, u * D), (W, v, u * D)][side])
    pts = [floor, np.array(walls)]
    if with_bed:   # 2.0 x 1.6 x 0.55 bed, head against the z=0 wall, centred
        pts.append(box_surface(rng, W / 2 - 0.8, W / 2 + 0.8, 0, 0.55, 0.0, 2.0, 30000))
    p = np.vstack(pts) + rng.normal(0, 0.005, (sum(len(a) for a in pts), 3))
    cams = np.array([[W / 2 + math.cos(a), 1.4, D / 2 + math.sin(a)] for a in np.linspace(0, 6, 12)])
    return p, cams


def scrambled(p, cams, s=0.37, yaw=0.6, tilt=0.15, shift=(3, -1, 2)):
    """What a video reconstruction gives: unknown scale, rotation and origin."""
    def rot(axis, a):
        c, s_ = math.cos(a), math.sin(a)
        if axis == "x": return np.array([[1, 0, 0], [0, c, -s_], [0, s_, c]])
        return np.array([[c, 0, s_], [0, 1, 0], [-s_, 0, c]])
    R = rot("x", tilt) @ rot("y", yaw)
    up = R @ np.array([0, 1, 0.0])
    return (p @ R.T) * s + shift, (cams @ R.T) * s + shift, up


def test_lidar_room_is_measured_and_bed_found():
    p, _ = synthetic_room()
    room, q = analyze(p, source="lidar")
    assert sorted([room.width, room.depth]) == pytest.approx(sorted([W, D]), abs=0.12)
    beds = [e for e in room.existing if e["guess"] == "bed"]
    assert len(beds) == 1 and beds[0]["h"] == pytest.approx(0.55, abs=0.06)
    assert abs(np.percentile(q[:, 1], 1)) < 0.03          # floor at y = 0


def test_video_room_scale_from_phone_height():
    p, cams = synthetic_room(with_bed=False)
    sp, sc, up = scrambled(p, cams)
    room, _ = analyze(sp, source="video", up_hint=up, cam_centers=sc)
    assert sorted([room.width, room.depth]) == pytest.approx(sorted([W, D]), rel=0.05)
    assert "phone" in room.scale_source


def test_video_room_scale_from_known_width():
    p, cams = synthetic_room(with_bed=False)
    sp, _, up = scrambled(p, cams)
    room, _ = analyze(sp, source="video", up_hint=up, known_width=4.5)
    assert max(room.width, room.depth) == pytest.approx(4.5, rel=0.03)


# ---------------------------------------------------------------- planner with a fake catalog
CATALOG = {
    "SOFA": [(210, 90, 80), (180, 88, 78)], "BED": [(160, 210, 100)], "RUG": [(240, 170, 1), (150, 210, 1)],
    "TABLE": [(110, 60, 45), (50, 45, 60), (45, 40, 55)], "LAMP": [(35, 35, 160), (30, 30, 50)],
    "CHAIR": [(80, 80, 85), (60, 60, 90)], "PLANTER": [(35, 35, 70)], "PILLOW": [(45, 15, 45)],
    "PLUSH_TOY": [(28, 22, 35), (25, 20, 30)], "DRESSER": [(120, 45, 80)], "SHELF": [(80, 35, 180)],
    "BEAN_BAG_CHAIR": [(80, 80, 70)], "DESK": [(120, 60, 75)],
}


def fake_search(q, types, max_w, max_d, max_h, k):
    out = []
    for t in types:
        for i, (w, d, h) in enumerate(CATALOG.get(t, [])):
            if (max_w is None or w <= max_w) and (max_d is None or d <= max_d) and (max_h is None or h <= max_h):
                out.append({"id": f"{t}-{i}", "title": f"{t} {i}", "product_type": t, "width_cm": w, "depth_cm": d,
                            "height_cm": h, "ar_model_url": None, "similarity": 0.7})
    return out[:k]


def overlaps(a, b):
    def ext(it):
        w, _, d = it["size"]
        q = round(it["rotation"] / (math.pi / 2)) % 2
        return (d, w) if q else (w, d)
    (aw, ad), (bw, bd) = ext(a), ext(b)
    return abs(a["position"][0] - b["position"][0]) * 2 < aw + bw - 0.02 and \
           abs(a["position"][2] - b["position"][2]) * 2 < ad + bd - 0.02


def test_living_room_plan_is_sensible():
    p, _ = synthetic_room(with_bed=False)
    room, _ = analyze(p, source="lidar")
    plan = Planner(room, "cozy mid-century living room", fake_search).plan()
    slots = [i["slot"] for i in plan["items"]]
    assert plan["room_type"] == "living"
    assert slots[0] == "sofa" and {"rug", "coffee_table", "floor_lamp"} <= set(slots)
    assert "pillow" in slots                                     # cozy adds pillows
    floor = [i for i in plan["items"] if i["layer"] == "floor"]
    assert not any(overlaps(a, b) for i, a in enumerate(floor) for b in floor[i + 1:])
    sofa = plan["items"][0]
    assert "wall" in sofa["reason"]
    for it in floor:                                             # everything inside the room
        x, _, z = it["position"]
        assert room.x0 - 0.05 <= x <= room.x0 + room.width + 0.05 and room.z0 - 0.05 <= z <= room.z0 + room.depth + 0.05


def test_bedroom_builds_around_existing_bed_and_cute_adds_plush():
    p, _ = synthetic_room(with_bed=True)
    room, _ = analyze(p, source="lidar")
    plan = Planner(room, "cute cozy bedroom", fake_search).plan()
    assert plan["room_type"] == "bedroom"
    bed = plan["items"][0]
    assert bed["slot"] == "bed" and bed["existing"] and "already have" in bed["reason"]
    slots = [i["slot"] for i in plan["items"]]
    assert slots.count("nightstand") == 2 and "plush" in slots
    plush = next(i for i in plan["items"] if i["slot"] == "plush")
    assert plush["position"][1] == pytest.approx(bed["size"][1], abs=0.02)   # on top of the scanned bed


def test_minimal_vibe_is_sparse():
    p, _ = synthetic_room(with_bed=False)
    room, _ = analyze(p, source="lidar")
    assert len(slots_for("minimal japandi living room", "living", room)) <= 4
