"""Rules-based room planner: scanned Room + vibe -> which products go where, and why.

No LLM. A room template (living / bedroom / office / nursery) lists slots in dependency order
(sofa -> rug -> coffee table -> lamp ...). The vibe adds or drops slots (cute -> plushies, plants ->
planters, minimal -> fewer things). For each slot the planner finds a pose that fits the free floor
(against the longest clear wall, in a corner, beside / in front of an anchor, on top of a seat),
then asks the vector search for vibe-matching products small enough for that spot, and keeps the
first whose real 3D footprint actually fits. Existing furniture found in the scan is kept and built
around ("you already have a bed here").
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from analyze import CELL, Room
from glb_bounds import glb_size

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
HALF_PI = math.pi / 2


# ---------------------------------------------------------------- poses on the grid
@dataclass
class Placed:
    slot: str
    x: float
    z: float
    y: float
    rot: float                     # radians about +y; model front is +z
    w: float                       # model width  (local x), metres, after scale
    d: float                       # model depth  (local z)
    h: float
    layer: str                     # "floor" blocks, "flat" (rugs) and "top" (on furniture) don't
    product: dict | None = None
    scale: float = 1.0
    reason: str = ""
    wall: dict | None = None
    existing: bool = False
    alternatives: list = field(default_factory=list)

    @property
    def facing(self):
        return np.array([math.sin(self.rot), math.cos(self.rot)])

    @property
    def right(self):
        f = self.facing
        return np.array([f[1], -f[0]])

    def extent(self):   # world (x, z) extent of an axis-snapped footprint
        quarter = round(self.rot / HALF_PI) % 2
        return (self.d, self.w) if quarter else (self.w, self.d)


def snap(rot: float) -> float:
    return round(rot / HALF_PI) * HALF_PI


class Grid:
    def __init__(self, room: Room):
        self.room = room
        self.blocked = ~room.free.copy()
        self.rugs = np.zeros_like(self.blocked)

    def _cells(self, x, z, ex, ez):
        r = self.room
        i0, i1 = int((z - ez / 2 - r.z0) / CELL), int(math.ceil((z + ez / 2 - r.z0) / CELL))
        j0, j1 = int((x - ex / 2 - r.x0) / CELL), int(math.ceil((x + ex / 2 - r.x0) / CELL))
        return i0, i1, j0, j1

    def fits(self, x, z, ex, ez, layer="floor", tol=0.03) -> bool:
        r = self.room
        if x - ex / 2 < r.x0 - 0.02 or x + ex / 2 > r.x0 + r.width + 0.02 or \
           z - ez / 2 < r.z0 - 0.02 or z + ez / 2 > r.z0 + r.depth + 0.02:
            return False
        i0, i1, j0, j1 = self._cells(x, z, ex, ez)
        i0, j0 = max(i0, 0), max(j0, 0)
        if layer == "flat":   # a rug may go under furniture, but needs seen floor and no other rug
            seen = r.seen[i0:i1, j0:j1]
            return seen.size > 0 and seen.mean() > 0.8 and not self.rugs[i0:i1, j0:j1].any()
        cells = self.blocked[i0:i1, j0:j1]
        return cells.size > 0 and cells.mean() <= tol

    def take(self, p: Placed):
        if p.layer == "top":
            return
        ex, ez = p.extent()
        i0, i1, j0, j1 = self._cells(p.x, p.z, ex, ez)
        i0, j0 = max(i0, 0), max(j0, 0)
        (self.rugs if p.layer == "flat" else self.blocked)[i0:i1, j0:j1] = True

    def wall_run(self, wall: dict, band: float = 0.5) -> float:
        """Longest stretch of free floor along a wall (metres)."""
        r = self.room
        (ax, az), (bx, bz), (nx, nz) = wall["a"], wall["b"], wall["normal"]
        n = max(2, int(wall["length"] / CELL))
        best = cur = 0
        for k in range(n):
            t = (k + 0.5) / n
            x, z = ax + (bx - ax) * t + nx * band / 2, az + (bz - az) * t + nz * band / 2
            ok = self.fits(x, z, CELL if nx == 0 else band, band if nx == 0 else CELL)
            cur = cur + 1 if ok else 0
            best = max(best, cur)
        return best * CELL


# ---------------------------------------------------------------- vibe -> room type + slots
SLOT_LIB = {  # key: (product types, search hint, layer)
    "sofa": (["SOFA"], "sofa", "floor"),
    "bed": (["BED", "BED_FRAME"], "bed", "floor"),
    "desk": (["DESK"], "desk", "floor"),
    "rug": (["RUG"], "area rug", "flat"),
    "coffee_table": (["TABLE"], "coffee table", "floor"),
    "side_table": (["TABLE"], "small side table end table", "floor"),
    "nightstand": (["TABLE", "CABINET", "HOME_FURNITURE_AND_DECOR"], "nightstand bedside table", "floor"),
    "floor_lamp": (["LAMP"], "floor lamp", "floor"),
    "table_lamp": (["LAMP"], "table lamp", "top"),
    "armchair": (["CHAIR"], "accent armchair", "floor"),
    "desk_chair": (["CHAIR"], "desk chair office chair", "floor"),
    "dresser": (["DRESSER", "CABINET"], "dresser chest of drawers", "floor"),
    "shelf": (["SHELF"], "bookshelf shelving", "floor"),
    "planter": (["PLANTER", "ARTIFICIAL_PLANT"], "planter plant pot", "floor"),
    "bean_bag": (["BEAN_BAG_CHAIR"], "bean bag", "floor"),
    "pillow": (["PILLOW"], "throw pillow cushion", "top"),
    "plush": (["PLUSH_TOY"], "plush toy stuffed animal", "top"),
    "floor_plush": (["PLUSH_TOY"], "plush toy stuffed animal", "floor"),
    "vase": (["VASE"], "vase", "top"),
}

TEMPLATES = {
    "living": ["sofa", "rug", "coffee_table", "floor_lamp", "side_table", "armchair", "planter"],
    "bedroom": ["bed", "nightstand", "nightstand", "table_lamp", "rug", "dresser", "planter"],
    "office": ["desk", "desk_chair", "shelf", "floor_lamp", "planter", "rug"],
    "nursery": ["rug", "bean_bag", "shelf", "floor_plush", "floor_plush", "floor_plush", "floor_lamp", "planter"],
}

ROOM_WORDS = [("bedroom", r"bed ?room|sleep|bed\b"), ("office", r"office|study|work ?space|desk"),
              ("nursery", r"nursery|kids?'? ?room|playroom|baby|child")]


def room_type_for(vibe: str, room: Room) -> tuple[str, str]:
    v = vibe.lower()
    for name, pat in ROOM_WORDS:
        if re.search(pat, v):
            return name, f"you said “{re.search(pat, v).group(0)}”"
    if any(e["guess"] == "bed" for e in room.existing):
        return "bedroom", "the scan has a bed-sized object"
    if any(e["guess"] == "desk or table" for e in room.existing) and room.width * room.depth < 10:
        return "office", "small room with a desk-sized object"
    return "living", "default for a room this size"


def slots_for(vibe: str, rtype: str, room: Room) -> list[str]:
    v = vibe.lower()
    slots = list(TEMPLATES[rtype])
    area = room.width * room.depth
    if area < 8:                                   # small room: drop the extras
        slots = [s for s in slots if s not in ("armchair", "side_table", "dresser", "shelf")]
    if re.search(r"minimal|zen|japandi|clean|sparse|simple", v):
        slots = [s for s in slots if s not in ("side_table", "armchair", "planter", "pillow", "plush", "vase")][:4]
    if re.search(r"cute|kawaii|playful|kid|plush|teddy|soft|adorable|whimsical", v):
        seat = "plush" if rtype in ("living", "bedroom") else "floor_plush"
        slots += [seat, seat, "pillow"] + (["bean_bag"] if "bean_bag" not in slots and area >= 10 else [])
    if re.search(r"cozy|cosy|hygge|warm|snug|comfy", v):
        slots += ["pillow", "pillow"] + (["rug"] if "rug" not in slots else [])
    if re.search(r"plant|green|jungle|botanical|boho|biophilic|natural|garden", v):
        slots += ["planter", "planter"]
    if re.search(r"vase|flower|floral", v):
        slots += ["vase"]
    return slots


# ---------------------------------------------------------------- planner
class Planner:
    def __init__(self, room: Room, vibe: str, search_fn, rtype: str | None = None):
        """search_fn(query, types, max_w_cm, max_d_cm, max_h_cm, k) -> product rows (with ar_model_url)."""
        self.room, self.vibe, self.search = room, vibe.strip(), search_fn
        self.grid = Grid(room)
        if rtype:
            self.rtype, self.rtype_why = rtype, "you picked it"
        else:
            self.rtype, self.rtype_why = room_type_for(self.vibe, room)
        self.placed: list[Placed] = []
        self.skipped: list[dict] = []
        self.used: set[str] = set()
        self.centre = np.array([room.x0 + room.width / 2, room.z0 + room.depth / 2])

    # products ---------------------------------------------------------
    def footprint(self, p: dict):
        """Real (w, d, h, scale) of the product's AR model, rescaled to its listing like the viewer does."""
        size = glb_size(str(MODELS_DIR / Path(p["ar_model_url"]).name)) if p.get("ar_model_url") else None
        listing = [v / 100 for v in (p.get("width_cm"), p.get("depth_cm"), p.get("height_cm")) if v]
        if not size:
            w, d, h = (p.get("width_cm") or 50) / 100, (p.get("depth_cm") or 50) / 100, (p.get("height_cm") or 50) / 100
            return w, d, h, 1.0
        s = 1.0
        if listing and max(size) > 0:
            r = max(listing) / max(size)
            if r < 0.75 or r > 1.33:
                s = r
        return size[0] * s, size[2] * s, size[1] * s, s

    def candidates(self, slot: str, max_w=None, max_d=None, max_h=None, k=10):
        types, hint, _ = SLOT_LIB[slot]
        q = f"{hint}. {self.vibe}" if self.vibe else hint
        cm = lambda v: None if v is None else round(v * 100, 1)
        rows = self.search(q, types, cm(max_w), cm(max_d), cm(max_h), k)
        if not rows and max_w:   # listing dims can be swapped: retry with the larger side as the limit
            big = max(max_w, max_d or 0)
            rows = self.search(q, types, cm(big), cm(big), cm(max_h), k)
        return [r for r in rows if r["id"] not in self.used]

    # pose generators: yield (x, z, rot, wall) for a model of size (w, d) ------------------
    def poses_against_wall(self, w, d, prefer_far_from=None):
        walls = sorted(self.room.walls(), key=lambda wl: -self.grid.wall_run(wl))
        if prefer_far_from is not None:
            walls.sort(key=lambda wl: -np.linalg.norm(np.add(wl["a"], wl["b"]) / 2 - prefer_far_from))
        for wl in walls:
            (ax, az), (bx, bz), (nx, nz) = wl["a"], wl["b"], wl["normal"]
            rot = math.atan2(nx, nz)
            L = wl["length"]
            for off in sorted(np.arange(-L / 2 + w / 2, L / 2 - w / 2 + 1e-6, 0.05), key=abs):
                t = 0.5 + off / L
                x = ax + (bx - ax) * t + nx * (d / 2 + 0.04)
                z = az + (bz - az) * t + nz * (d / 2 + 0.04)
                yield x, z, rot, wl

    def poses_corner(self, w, d):
        r, m = self.room, 0.06
        corners = [(r.x0, r.z0, 1, 1), (r.x0 + r.width, r.z0, -1, 1), (r.x0, r.z0 + r.depth, 1, -1),
                   (r.x0 + r.width, r.z0 + r.depth, -1, -1)]
        def emptiness(c):
            return min([np.hypot(c[0] - p.x, c[1] - p.z) for p in self.placed if p.layer == "floor"] or [9])
        for cx, cz, sx, sz in sorted(corners, key=lambda c: -emptiness(c)):
            for inset in (0.0, 0.15, 0.3):
                x, z = cx + sx * (w / 2 + m + inset), cz + sz * (d / 2 + m + inset)
                rot = snap(math.atan2(self.centre[0] - x, self.centre[1] - z))
                yield x, z, rot, None

    def poses_center(self, w, d):
        rot = 0.0 if self.room.width >= self.room.depth else HALF_PI
        for dx, dz in [(0, 0), (0.3, 0), (-0.3, 0), (0, 0.3), (0, -0.3)]:
            yield self.centre[0] + dx, self.centre[1] + dz, rot, None

    def poses_relative(self, a: Placed, w, d, where: str):
        f, rt = a.facing, a.right
        if where == "front":                                   # coffee table / rug in front of a sofa
            for gap in (0.45, 0.35, 0.55, 0.25):
                c = np.array([a.x, a.z]) + f * (a.d / 2 + gap + d / 2)
                yield c[0], c[1], a.rot, None
        elif where == "under_front":                           # rug half under the sofa's front legs
            for back in (0.25, 0.1, 0.4):
                c = np.array([a.x, a.z]) + f * (a.d / 2 - back + d / 2)
                yield c[0], c[1], a.rot, None
        elif where == "beside":                                # lamp / side table / nightstand at either end
            for side in (1, -1):
                c = np.array([a.x, a.z]) + rt * side * (a.w / 2 + 0.06 + w / 2) - f * (a.d / 2 - d / 2 - 0.02)
                yield c[0], c[1], a.rot, a.wall
        elif where == "facing_side":                           # armchair at the side, turned to face the middle
            for side in (1, -1):
                c = np.array([a.x, a.z]) + rt * side * (a.w / 2 + 0.35 + d / 2) + f * (a.d / 2 + 0.3)
                rot = snap(math.atan2(-rt[0] * side, -rt[1] * side))
                yield c[0], c[1], rot, None
        elif where == "chair_at":                              # desk chair pulled up to the desk
            c = np.array([a.x, a.z]) + f * (a.d / 2 + d / 2 - 0.15)
            yield c[0], c[1], a.rot + math.pi, None

    # placing ----------------------------------------------------------
    def anchor(self, *keys) -> Placed | None:
        for p in self.placed:
            if p.slot in keys:
                return p
        return None

    def try_slot(self, slot: str) -> Placed | None:
        types, hint, layer = SLOT_LIB[slot]
        sofa_or_bed = self.anchor("sofa", "bed")
        rule, a, limits = self.rule_for(slot, sofa_or_bed)
        if rule is None:
            return None
        cands = self.candidates(slot, *limits)
        if slot in ("planter", "floor_lamp"):          # on the floor, taller reads better: prefer >= 40 cm
            cands.sort(key=lambda r: (r.get("height_cm") or 0) < 40)
        for prod in cands:
            w, d, h, s = self.footprint(prod)
            extra = 0.0
            if slot == "rug" and d > w:                # lay the rug's long side along the sofa / bed
                extra = HALF_PI
            lw, ld = (d, w) if extra else (w, d)       # logical footprint the pose rules work with
            if layer == "top":
                pose = self.on_top(slot, a, w, d)
                if pose is None:
                    continue
                x, z, y, rot = pose
                return self.commit(slot, prod, x, z, rot, None, w, d, h, s, layer, y=y, anchor=a)
            gen = (self.poses_against_wall(lw, ld) if rule == "wall"
                   else self.poses_against_wall(lw, ld, prefer_far_from=np.array([a.x, a.z])) if rule == "far_wall"
                   else self.poses_corner(lw, ld) if rule == "corner"
                   else self.poses_center(lw, ld) if rule == "center"
                   else self.poses_relative(a, lw, ld, rule))
            for x, z, rot, wl in gen:
                ex, ez = (ld, lw) if round(rot / HALF_PI) % 2 else (lw, ld)
                if self.grid.fits(x, z, ex, ez, layer):
                    return self.commit(slot, prod, x, z, rot + extra, wl, w, d, h, s, layer, anchor=a)
        return None

    def rule_for(self, slot, a):
        """(placement rule, anchor, (max_w, max_d, max_h) for the search)."""
        best_run = max(self.grid.wall_run(wl) for wl in self.room.walls())
        if slot in ("sofa", "bed", "desk"):
            return "wall", None, (min(best_run - 0.1, 3.2), 2.3 if slot == "bed" else 1.2, None)
        if slot in ("dresser", "shelf"):
            return ("far_wall" if a else "wall"), a, (min(best_run - 0.1, 1.8), 0.6, None)
        if slot == "rug":
            if a and a.slot == "sofa":
                return "under_front", a, (min(3.2, a.w + 0.8), min(2.5, self.room.depth / 2), None)
            if a and a.slot == "bed":
                return "under_front", a, (min(2.8, a.w + 0.6), 1.8, None)
            return "center", None, (min(2.4, self.room.width * 0.6), min(1.8, self.room.depth * 0.6), None)
        if slot == "coffee_table":
            return ("front", a, (min(1.4, a.w * 0.65), 0.8, 0.55)) if a and a.slot == "sofa" else (None, None, None)
        if slot in ("side_table", "nightstand"):
            return ("beside", a, (0.6, 0.6, 0.75)) if a else (None, None, None)
        if slot == "floor_lamp":
            return ("beside", a, (0.6, 0.6, None)) if a else ("corner", None, (0.6, 0.6, None))
        if slot == "armchair":
            ct = self.anchor("coffee_table") or a
            return ("facing_side", ct, (1.0, 1.0, None)) if ct else ("corner", None, (1.0, 1.0, None))
        if slot == "desk_chair":
            d = self.anchor("desk")
            return ("chair_at", d, (0.75, 0.75, None)) if d else (None, None, None)
        if slot in ("planter", "bean_bag", "floor_plush"):
            return "corner", None, ((0.6, 0.6, None) if slot == "planter" else (1.0, 1.0, None) if slot == "bean_bag"
                                    else (0.5, 0.5, 0.6))
        if slot in ("pillow", "plush"):
            seat = self.anchor("sofa", "bed", "armchair", "bean_bag")
            return ("top", seat, (0.6, 0.4, 0.6)) if seat else (None, None, None)
        if slot == "table_lamp":
            ns = self.anchor("nightstand", "side_table", "desk")
            return ("top", ns, (0.45, 0.45, 0.75)) if ns else (None, None, None)
        if slot == "vase":
            t = self.anchor("coffee_table", "side_table", "nightstand", "dresser", "desk")
            return ("top", t, (0.35, 0.35, 0.6)) if t else (None, None, None)
        return None, None, (None, None, None)

    def on_top(self, slot, a: Placed, w, d):
        """Spot on a seat / surface: (x, z, y, rot)."""
        if a is None:
            return None
        if slot == "table_lamp" or slot == "vase":
            y = a.h
            spots = [(0.0, 0.0)]
        elif a.existing:                          # scanned furniture: its measured height IS the top surface
            y = a.h
            spots = [(-0.25, -0.3), (0.25, -0.3), (0.0, -0.2), (-0.1, 0.0)]
        elif a.slot == "bed":                     # catalog bed: height includes the headboard
            y = min(0.62, a.h * 0.5)
            spots = [(-0.25, -0.3), (0.25, -0.3), (0.0, -0.2), (-0.1, 0.0)]
        else:                                     # sofa / armchair / bean bag seat
            y = min(0.5, a.h * 0.55)
            spots = [(-0.33, -0.12), (0.33, -0.12), (0.0, -0.05), (-0.15, 0.05)]
        taken = sum(1 for p in self.placed if p.layer == "top" and p.reason.endswith(a.slot))
        if taken >= len(spots) or w > a.w * 0.6:
            return None
        u, v = spots[taken]
        c = np.array([a.x, a.z]) + a.right * (u * a.w) + a.facing * (v * a.d)
        return c[0], c[1], y, a.rot

    def commit(self, slot, prod, x, z, rot, wl, w, d, h, s, layer, y=0.0, anchor=None) -> Placed:
        p = Placed(slot, float(x), float(z), float(y), float(rot), w, d, h, layer, prod, s, wall=wl)
        p.reason = self.reason(p, anchor)
        self.placed.append(p)
        self.grid.take(p)
        self.used.add(prod["id"])
        return p

    def reason(self, p: Placed, a: Placed | None) -> str:
        what = p.slot.replace("_", " ")
        if p.slot in ("sofa", "bed", "desk", "dresser", "shelf") and p.wall:
            return f"Against the {p.wall['length']:.1f} m {p.wall['name']} wall, the longest clear wall"
        if p.layer == "top" and a:
            return f"Sits on the {a.slot.replace('_', ' ')}"
        if a is not None:
            rel = {"rug": "under the front of", "coffee_table": "in front of", "armchair": "facing",
                   "desk_chair": "at"}.get(p.slot, "beside")
            return f"{what.capitalize()} {rel} the {a.slot.replace('_', ' ')}"
        return f"Fills the emptiest corner" if p.slot in ("planter", "bean_bag", "floor_plush", "floor_lamp", "rug") else what

    def use_existing(self):
        """Treat a scanned sofa/bed as already there: build around it instead of buying one."""
        want = {"living": "sofa", "bedroom": "bed"}.get(self.rtype)
        for e in self.room.existing:
            if want and e["guess"] == want and not self.anchor(want):
                c = np.array([e["x"], e["z"]])
                to_c = self.centre - c
                rot = snap(math.atan2(to_c[0], to_c[1]))
                w, d = (e["w"], e["d"]) if round(rot / HALF_PI) % 2 == 0 else (e["d"], e["w"])
                p = Placed(want, e["x"], e["z"], 0.0, rot, w, d, e["h"], "floor", None, existing=True,
                           reason=f"You already have a {want} here, so the plan builds around it")
                self.placed.append(p)

    def plan(self) -> dict:
        self.use_existing()
        for slot in slots_for(self.vibe, self.rtype, self.room):
            if slot in ("sofa", "bed") and self.anchor(slot):
                continue
            if self.rule_for(slot, self.anchor("sofa", "bed"))[0] is None:
                needs = {"coffee_table": "a sofa", "side_table": "a sofa or bed", "nightstand": "a bed",
                         "desk_chair": "a desk", "pillow": "a seat", "plush": "a seat", "table_lamp": "a table",
                         "vase": "a table"}.get(slot, "an anchor piece")
                self.skipped.append({"slot": slot, "why": f"needs {needs} to go with, and none was placed"})
                continue
            try:
                p = self.try_slot(slot)
            except Exception as e:  # one bad slot shouldn't sink the plan
                p = None
                self.skipped.append({"slot": slot, "why": f"error: {type(e).__name__}"})
                continue
            if p is None:
                self.skipped.append({"slot": slot, "why": "no product fits the free space there"})
            else:
                p.alternatives = self.alternatives(p)
        return self.to_json()

    def alternatives(self, p: Placed, n=4):
        """Other products that fit the very same spot (for the swap button)."""
        out = []
        for prod in self.candidates(p.slot, p.w + 0.05, p.d + 0.05, None if p.layer != "top" else p.h + 0.1, k=12):
            if prod["id"] == p.product["id"]:
                continue
            w, d, h, s = self.footprint(prod)
            if w <= p.w + 0.05 and d <= p.d + 0.05:
                out.append(self.product_json(prod, s))
            if len(out) >= n:
                break
        return out

    @staticmethod
    def product_json(prod, s=1.0):
        keep = ("id", "title", "product_type", "style", "color", "width_cm", "depth_cm", "height_cm",
                "image_url", "ar_model_url", "url", "similarity")
        return {**{k: prod.get(k) for k in keep}, "scale": s}

    def to_json(self) -> dict:
        return {
            "room_type": self.rtype, "room_type_why": self.rtype_why, "vibe": self.vibe,
            "items": [{
                "slot": p.slot, "position": [round(p.x, 3), round(p.y, 3), round(p.z, 3)], "rotation": round(p.rot, 4),
                "size": [round(p.w, 3), round(p.h, 3), round(p.d, 3)], "layer": p.layer, "existing": p.existing,
                "reason": p.reason, "product": None if p.existing else self.product_json(p.product, p.scale),
                "alternatives": p.alternatives,
            } for p in self.placed],
            "skipped": self.skipped,
        }
