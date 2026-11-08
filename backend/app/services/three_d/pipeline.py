"""See your room restyled with the products from a search.

    context  gemini-3-flash-preview looks at the photo AND the brief; room_type (the brief's own word for
             it wins over a guess from a bare/ambiguous photo) + style + what it's missing. Re-runs the
             search with the brief and that context, so an empty bedroom gets bed/nightstand candidates
             instead of whatever the brief's words alone matched. Falls back to the caller's product list
             on any failure (missing Vertex access, Supabase down, etc.) rather than blocking.
    design   Gemini 3.1 Pro looks at the photo + the brief + the search results; picks which products go
             where (floor zone + layout) and up to 3 styling tweaks that are NOT products
    place    true-size placement from the scene camera: zone -> floor point -> product box with its real
             dimensions -> screen box ("red box guide"), with layouts against_wall / center / in_front_of /
             beside / under / on_top_of and no overlaps
    render   gemini-3.1-flash-image draws each product inside its box, from the product photo
    verify   Gemini 3 Flash finds each product in the render and compares it with its box; one retry with
             feedback if off target or if the room itself was redrawn; the best attempt wins

Model choices come from side-by-side tests on real phone photos: Gemini 3.1 Pro for the design step picked
clearly better products than Flash; gemini-3.1-flash-image kept sizes closer to the true-size boxes than
gemini-3-pro-image at half the time. A run takes ~30-60 s (longer when Vertex rate-limits).
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import storage
from .scene import Camera
from .schemas import Design, Detection, Extras, RoomContext
from .vertex import generate, generate_json

log = logging.getLogger(__name__)

DESIGN_MODEL = os.environ.get("THREE_D_DESIGN_MODEL", "gemini-3.1-pro-preview")
FAST_MODEL = os.environ.get("THREE_D_FAST_MODEL", "gemini-3-flash-preview")
IMAGE_MODEL = os.environ.get("THREE_D_IMAGE_MODEL", "gemini-3.1-flash-image")
MAX_PICKS = 4
DRIFT_LIMIT = 30.0  # mean colour change outside the products; above this the AI redrew the room
CONTEXT_TIMEOUT_S = 30.0  # bounds products_for_room(); see its docstring for why this matters
# Product photos are only downloaded from the catalogue's image hosts.
IMAGE_HOSTS = {"amazon-berkeley-objects.s3.amazonaws.com", "media.sketchfab.com"}


# ---------------------------------------------------------------- products

def _size_cm(p: dict) -> str:
    w, d = sorted([p["width_cm"], p["depth_cm"]], reverse=True)
    return f"{w:.0f} x {d:.0f} x {p['height_cm']:.0f} cm"


def _is_rug(p: dict) -> bool:
    return "rug" in (p.get("category") or "").lower()


def fetch_product_image(url: str | None) -> bytes | None:
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "BuyByFit"}), timeout=10) as r:
            data = r.read(8_000_000)
    except Exception:
        return None
    return data if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" else None


# ---------------------------------------------------------------- room context

def quick_room_context(photo: bytes, brief: str) -> dict:
    """One fast, cheap call: what kind of room this is and what it looks like it needs.

    Takes the brief, not just the photo: a generic or ambiguous room photo (bare walls, no distinctive
    furniture or layout cues) gives Gemini little to infer room_type from visually, but the user may have
    already said exactly what it is ("a warm minimalist bedroom..."). Ignoring that and guessing from the
    image alone is strictly worse information, so the user's stated room type -- when they gave one --
    overrides a visual guess rather than competing with it."""
    return generate_json(FAST_MODEL, [photo, f"""Look at this phone photo of a room.
The user's brief: "{brief}"

room_type: what kind of room this is. If the brief states or clearly implies a room type (e.g. "bedroom",
  "home office"), use that -- it's a stronger signal than guessing from a bare or ambiguous photo. Only
  infer from the photo alone if the brief doesn't say.
style: its current colors/materials/style, briefly (from the photo).
needs: up to 4 furniture or decor categories this room is missing or could use, most important first, for
  THAT room_type. An empty or sparse room needs real furniture (a bed for a bedroom, a sofa for a living
  room, a desk for an office) before decor (lamps, art, plants)."""],
                       schema=RoomContext, thinking="minimal")


def products_for_room(photo: bytes, brief: str, fallback_products: list[dict]) -> tuple[list[dict], list[str]]:
    """Re-run the search with the room's own context folded into the brief, so the candidate list actually
    fits what the room needs (not just the brief's words in isolation). Falls back to `fallback_products`
    (whatever the caller already had on screen), with no `needs` hint, if the room-context call or the
    search itself fails, or doesn't finish within CONTEXT_TIMEOUT_S -- this must never be the reason a
    visualization request stalls. Bounded with a timeout deliberately: jobs.py runs one visualization at a
    time, so a slow call here (e.g. the embedding model's first, one-time download on a fresh instance)
    would otherwise block every other visualization request behind this one indefinitely.

    Returns (products, needs): `needs` (e.g. ["bed", "nightstand"]) is passed on to design() as an explicit
    priority hint, separately from folding it into the search text -- a good embedding match for a
    nightstand can still outrank a so-so match for a missing bed, so design() needs to be told directly
    what the room is actually missing, not just have it diluted into the search query."""
    # Not a `with` block: ThreadPoolExecutor.__exit__ calls shutdown(wait=True), which would block here
    # until the submitted call actually finishes -- defeating the timeout below if it's the slow one.
    # shutdown(wait=False) lets a still-running call become an orphaned background thread instead; it
    # can't be killed, but it no longer blocks this function (or the caller's single job slot) from
    # returning on time.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        products, needs = pool.submit(_search_for_room, photo, brief).result(timeout=CONTEXT_TIMEOUT_S)
    except Exception:
        log.exception("room-context search failed or timed out; using the caller's product list instead")
        return fallback_products, []
    finally:
        pool.shutdown(wait=False)
    log.info("room context: needs=%s, %d candidates", needs, len(products))
    return (products or fallback_products), needs


def _search_for_room(photo: bytes, brief: str) -> tuple[list[dict], list[str]]:
    context = quick_room_context(photo, brief)
    needs = context["needs"]
    enriched_brief = (
        f'{brief}. The room is a {context["room_type"]} that currently looks {context["style"]} '
        f"and could use: {', '.join(needs) or 'furniture'}."
    )
    from app.services.logic.recommend import recommend  # same deployment, in-process call

    candidates = recommend(enriched_brief, {}, limit=24)

    products = [
        {
            "id": p["id"],
            "name": p["name"],
            "category": p.get("category"),
            "width_cm": p["dimensions_cm"]["width"],
            "depth_cm": p["dimensions_cm"]["depth"],
            "height_cm": p["dimensions_cm"]["height"],
            "image_url": p.get("image_url"),
            "product_url": p.get("product_url"),
        }
        for p in candidates
        if p["dimensions_cm"]["width"] and p["dimensions_cm"]["depth"] and p["dimensions_cm"]["height"]
    ]
    return products, needs


# ---------------------------------------------------------------- design

_FURNITURE_WORDS = (
    "bed", "sofa", "couch", "sectional", "loveseat", "armchair", "chair", "table", "desk", "dresser",
    "wardrobe", "armoire", "cabinet", "bookshelf", "bookcase", "nightstand", "night stand", "ottoman",
    "bench", "shelving", "shelf", "console",
)


def _mentions_furniture(instruction: str) -> bool:
    """A tweak is meant to be non-furniture (see design()'s prompt); this is the Python-side backstop
    for when the model names a furniture item in one anyway, which render() would otherwise draw into
    the image with no real product behind it."""
    lowered = instruction.lower()
    return any(word in lowered for word in _FURNITURE_WORDS)


def design(photo: bytes, brief: str, products: list[dict], needs: list[str] | None = None,
           room_cm: dict | None = None) -> dict:
    listing = "\n".join(f"p{i} | {p['name'][:90]} | {p.get('category') or 'furniture'} | {_size_cm(p)} (W x D x H)"
                        for i, p in enumerate(products, 1))
    room_size_hint = ""
    if room_cm:
        w_cm, d_cm = room_cm["width"], room_cm["depth"]
        room_size_hint = (
            f"\nThe user measured this room's actual floor dimensions: {w_cm:.0f} x {d_cm:.0f} cm. Use "
            "this as ground truth over your own visual guess -- it's a real measurement, not an estimate. "
            f"Draw free_floor_zones sized consistently with it: if the room is empty or mostly empty, most "
            f"of that {w_cm:.0f} x {d_cm:.0f} cm floor is a usable zone, not just the small patch you'd "
            "casually sketch.\n"
        )
    needs_hint = (
        f"\nLooking at the room yourself, it most needs (in order): {', '.join(needs)}. A product that fills "
        "one of these is more important than one that only matches the brief's words more closely -- e.g. "
        "prefer the bed over a second side table, even if the side table's style match scored higher. If "
        "this list contains a product for the #1 need, you MUST include it as a pick -- do not describe it "
        "in a styling tweak instead. A tweak is not a substitute for an available real pick: only the picks "
        "list actually gets placed and rendered, so a bed mentioned only as a tweak means no bed appears.\n"
        if needs else ""
    )
    return generate_json(DESIGN_MODEL, [photo, f"""You are an interior designer looking at a phone photo of a room.
The user's brief: "{brief}".{room_size_hint}{needs_hint}
These products were already matched to the brief (reference | name | category | real size):
{listing}

1. Analyse the room. box_2d = [ymin, xmin, ymax, xmax] in 0-1000 image coordinates.
   free_floor_zones = visible empty floor areas where furniture could stand (the box covers the floor area).
   For a large or structural piece this list might call for (a bed, sofa, or wardrobe), draw that zone as
   the FULL floor space actually available along that wall, not a conservative patch around where you'd
   casually sketch it. The true-size check afterward is what actually enforces whether a product fits --
   if you draw the zone too small, a real-size bed or sofa gets rejected as "too big" even when the room
   genuinely has the floor space for it.
2. Pick at most {MAX_PICKS} products FROM THIS LIST that together best restyle the room toward the brief
   (complementary pieces: e.g. a desk and a chair, or a sofa, a rug and a lamp; not two of the same kind).
   Each stands on one free_floor_zone and must physically fit there at its real size.
   layout says how it stands:
     "against_wall"   its back to the wall/window at the far side of the zone (desks, sofas, shelves)
     "center"         free-standing in the middle of the zone (coffee tables, armchairs)
     "in_front_of:sX" facing pick sX from the camera side (a chair at its desk)
     "beside:sX"      next to pick sX on the floor (side tables, floor lamps)
     "under:sX"       a rug under pick sX and its group
     "on_top_of:sX"   on top of pick sX (table lamps, small decor)
   Order picks so a referenced pick comes first.
3. Up to 3 styling tweaks for things that are NOT products (plants, small decor, light colour, wall colour,
   declutter). A tweak must never describe a piece of furniture (no beds, tables, chairs, lamps, rugs,
   shelves, etc.) -- if you want a furniture item in the room, it belongs in picks, above, as an actual
   product reference, not as tweak text. Tweaks only ever get an instruction in words; nothing in a tweak
   is placed, sized, or guaranteed to appear in the final image."""], schema=Design)


# ---------------------------------------------------------------- placement (true size)

def _footprint(anchor, W, D, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return [(anchor[0] + px * c + pz * s, anchor[2] - px * s + pz * c)
            for px, pz in ((-W / 2, -D / 2), (W / 2, -D / 2), (W / 2, D / 2), (-W / 2, D / 2))]


def _overlap(a, b, tol=0.02):
    """Separating-axis test for two floor rectangles."""
    for poly in (a, b):
        for i in range(4):
            (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % 4]
            nx, nz = z2 - z1, x1 - x2
            n = math.hypot(nx, nz) or 1
            pa = [(x * nx + z * nz) / n for x, z in a]
            pb = [(x * nx + z * nz) / n for x, z in b]
            if max(pa) <= min(pb) + tol or max(pb) <= min(pa) + tol:
                return False
    return True


def place(pick: dict, product: dict, zone: dict, cam: Camera, placed: dict, room_cm: dict | None = None) -> dict:
    y0, x0, y1, x1 = [v / 1000 for v in zone["box_2d"]]
    cx = (x0 + x1) / 2
    far, mid = cam.floor_point(cx, y0 + 0.06 * (y1 - y0)), cam.floor_point(cx, (y0 + y1) / 2)
    if mid is None:
        return {"ok": False, "why": "zone is not on the visible floor"}
    far = mid if far is None else far
    w, d = sorted([product["width_cm"], product["depth_cm"]], reverse=True)  # catalogue W/D are often swapped
    W, D, H = w / 100, d / 100, product["height_cm"] / 100

    def toward_cam(p):
        v = np.array([cam.pos[0] - p[0], 0.0, cam.pos[2] - p[2]])
        return v / (np.linalg.norm(v) or 1)

    def face_cam(p):
        return math.atan2(cam.pos[0] - p[0], cam.pos[2] - p[2])  # model front (+Z) faces the camera

    kind, _, ref_id = str(pick.get("layout") or "center").partition(":")
    ref_id = ref_id.strip()
    ref = placed.get(ref_id) if ref_id else None
    is_rug = _is_rug(product) or kind == "under"
    if is_rug:
        H = min(H, 0.02)  # rugs lie flat (catalogue heights are often the rolled package)
    base_y = 0.0
    floor_items = [o for k, o in placed.items() if k != ref_id and not o["_flat"]]

    if kind == "in_front_of" and ref:  # staged like an interior photo: pulled out, turned ~25 degrees
        t = toward_cam(ref["_anchor"])
        lat = np.array([t[2], 0.0, -t[0]])
        anchor = ref["_anchor"] + t * (ref["_dims"][1] / 2 + D / 2 + 0.10) + lat * 0.15
        yaw = math.atan2(ref["_anchor"][0] - anchor[0], ref["_anchor"][2] - anchor[2]) + math.radians(25)
    elif kind == "beside" and ref:  # the side towards the zone's middle, else the free side
        t = toward_cam(ref["_anchor"])
        lat = np.array([t[2], 0.0, -t[0]])
        pref = 1.0 if float(np.dot(mid - ref["_anchor"], lat)) >= 0 else -1.0
        for side in (pref, -pref):
            anchor = ref["_anchor"] + lat * side * (ref["_dims"][0] / 2 + W / 2 + 0.08)
            yaw = face_cam(anchor)
            fp = _footprint(anchor, W, D, yaw)
            if not any(_overlap(fp, _footprint(o["_anchor"], *o["_dims"][:2], o["_yaw"])) for o in floor_items):
                break
    elif kind == "under" and ref:
        anchor = ref["_anchor"] + toward_cam(ref["_anchor"]) * 0.35
        yaw = ref["_yaw"]
    elif kind == "on_top_of" and ref:
        t = toward_cam(ref["_anchor"])
        lat = np.array([t[2], 0.0, -t[0]])
        anchor = ref["_anchor"] + lat * max(0.0, ref["_dims"][0] / 2 - W / 2 - 0.08)
        base_y = ref["_dims"][2]
        yaw = face_cam(anchor)
    elif kind == "against_wall":
        anchor = far + toward_cam(far) * (D / 2 + 0.03)
        yaw = face_cam(anchor)
    else:
        anchor = mid
        yaw = face_cam(anchor)

    flat = is_rug or kind == "on_top_of"
    if not flat:  # don't overlap floor-standing pieces
        for _ in range(4):
            fp = _footprint(anchor, W, D, yaw)
            if not any(_overlap(fp, _footprint(o["_anchor"], *o["_dims"][:2], o["_yaw"])) for o in floor_items):
                break
            anchor = anchor + toward_cam(anchor) * 0.25

    c, s = math.cos(yaw), math.sin(yaw)
    corners = [cam.project([anchor[0] + px * c + pz * s, base_y + py, anchor[2] - px * s + pz * c])
               for px in (-W / 2, W / 2) for pz in (-D / 2, D / 2) for py in (0, H)]
    if any(p is None for p in corners):
        return {"ok": False, "why": "would be behind the camera"}
    us, vs = [p[0] for p in corners], [p[1] for p in corners]
    box = [max(0, min(vs)) * 1000, max(0, min(us)) * 1000, min(1, max(vs)) * 1000, min(1, max(us)) * 1000]
    box_w, box_area = box[3] - box[1], (box[3] - box[1]) * (box[2] - box[0]) / 1e6
    # The zone box is Gemini's 2D guess at the room's scale; a user-measured room size is ground truth.
    # If this product's real footprint is a modest share of the room's actual floor area, trust that over
    # a zone that might just have been drawn too tightly, rather than reject a piece that genuinely fits.
    width_tolerance = 1.35
    if room_cm and (W * D) <= (room_cm["width"] / 100) * (room_cm["depth"] / 100) * 0.4:
        width_tolerance = 2.0
    if not is_rug and (box_w > (x1 - x0) * 1000 * width_tolerance or box_area > 0.45):
        return {"ok": False, "why": "too big for that spot"}
    return {"ok": True, "box": [round(float(v), 1) for v in box],
            "distance_m": round(float(np.hypot(anchor[0] - cam.pos[0], anchor[2] - cam.pos[2])), 2),
            "_anchor": anchor, "_dims": (W, D, H), "_yaw": yaw, "_flat": flat, "_rug": is_rug}


# ---------------------------------------------------------------- render + verify

def guide_image(photo: Image.Image, items: list[dict]) -> bytes:
    im = photo.copy()
    W, H = im.size
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", max(18, W // 30))
    except OSError:
        font = ImageFont.load_default()
    for n, it in enumerate(items, 1):
        y0, x0, y1, x1 = it["box"]
        dr.rectangle([x0 * W / 1000, y0 * H / 1000, x1 * W / 1000, y1 * H / 1000], outline=(255, 0, 0), width=max(4, W // 200))
        dr.text((x0 * W / 1000 + 6, y0 * H / 1000 + 4), str(n), fill=(255, 0, 0), font=font)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _aspect(w: int, h: int) -> str:
    options = {"1:1": 1, "3:4": 3 / 4, "4:3": 4 / 3, "9:16": 9 / 16, "16:9": 16 / 9, "2:3": 2 / 3, "3:2": 3 / 2}
    return min(options, key=lambda k: abs(options[k] - w / h))


def render(guide: bytes, items: list[dict], refs: list[bytes], tweaks: list[dict], vibe: str, aspect: str,
           feedback: str = "") -> bytes:
    lines = "\n".join(f"  box {n}: {it['product']['name'][:80]} ({_size_cm(it['product'])})"
                      + (f"; product photo = image {it['ref_index'] + 2}" if it.get("ref_index") is not None else "")
                      for n, it in enumerate(items, 1))
    tw = "\n".join(f"  - {t['type']}: {t['instruction']}" for t in tweaks) or "  - none"
    prompt = f"""Image 1 is a real phone photo of a room with numbered red rectangles drawn on it.
Images 2 to {1 + len(refs)} are product photos.
Return Image 1 as a real photograph restyled toward "{vibe}":
1. Furniture (MOST IMPORTANT, exact size): place each product standing on the floor inside its red rectangle.
   Its outer edges touch the rectangle's left, right and top sides and its feet stand on the bottom side.
   Nothing goes outside its rectangle. Each product must look EXACTLY like its product photo: same shape,
   same legs, same colours and materials (the product photo wins over the room's style). A rug lies flat on the floor.
{lines}
2. Styling tweaks (subtle, keep it believable):
{tw}
3. Keep the room's architecture, windows, walls, floor and camera framing exactly the same.
   Match light direction, white balance and phone-camera noise; add soft contact shadows.
   Remove every red rectangle and number. Do not add people, text, or any furniture or decor beyond what's
   listed above -- no extra rugs, pillows, throws, plants, lamps, or artwork, even if the room looks sparse
   or a styling tweak doesn't fully furnish it. Every piece you draw must be something the user can actually
   buy from this plan; inventing one they can't is worse than leaving the room looking unfinished.
{feedback}"""
    return generate(IMAGE_MODEL, [guide, *refs, prompt], image_out=True, aspect=aspect)


def _iou(a, b):
    y0, x0, y1, x1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, y1 - y0) * max(0, x1 - x0)
    area = lambda r: max(0, r[2] - r[0]) * max(0, r[3] - r[1])  # noqa: E731
    return inter / (area(a) + area(b) - inter + 1e-9)


def verify(render_png: bytes, items: list[dict]) -> list[dict]:
    names = "\n".join(f"{n}. {it['product']['name'][:80]}" for n, it in enumerate(items, 1))
    found = generate_json(FAST_MODEL, [render_png, f"""Find each of these products in the image:
{names}
box_2d tight around the whole piece of furniture (legs included), 0-1000 coordinates; found=false if absent."""],
                          schema=Detection, thinking="minimal")
    out = []
    for n, it in enumerate(items, 1):
        f = next((x for x in found["items"] if x["n"] == n), None)
        t = it["box"]
        if not f or not f["found"] or not f["box_2d"]:
            out.append({"n": n, "found": False})
            continue
        b = f["box_2d"]
        if it["_rug"]:  # flat, and catalogue rug sizes are unreliable: report, don't score
            out.append({"n": n, "found": True, "rug": True, "iou": None, "box_2d": [round(float(v), 1) for v in b]})
            continue
        tw, th = t[3] - t[1], t[2] - t[0]
        out.append({"n": n, "found": True, "box_2d": [round(float(v), 1) for v in b], "iou": round(_iou(t, b), 2),
                    "width_error_pct": round(100 * ((b[3] - b[1]) - tw) / tw, 1),
                    "height_error_pct": round(100 * ((b[2] - b[0]) - th) / th, 1)})
    return out


def find_extras(render_png: bytes, items: list[dict], tweaks: list[dict]) -> list[str]:
    """Image models are unreliable at negative instructions ("don't add X") -- render()'s prompt already
    tells it not to invent furniture, but that alone isn't enough to stop it (seen in practice: a rug drawn
    in with no product or tweak behind it). This checks the actual pixels afterward instead of just trusting
    the prompt, so a hallucinated, unpurchasable piece can be caught and penalised like a missing one is."""
    names = "\n".join(f"{n}. {it['product']['name'][:80]}" for n, it in enumerate(items, 1))
    approved = "\n".join(f"  - {t['instruction']}" for t in tweaks) or "  - none"
    found = generate_json(FAST_MODEL, [render_png, f"""This room should contain exactly these numbered products,
and nothing else new:
{names}

These approved styling touches are also expected (not products, but intentional -- don't flag them):
{approved}

List any OTHER furniture, rug, lamp, plant, or large decor visible that isn't one of the numbered products
and isn't explained by an approved styling touch above. Ignore the room's own pre-existing fixtures (windows,
built-in lighting already in the original photo, trim). Empty list if there's nothing extra."""],
                          schema=Extras, thinking="minimal")
    return [e["description"] for e in found["extras"]]


def room_drift(photo: Image.Image, render_png: bytes, items: list[dict]) -> float:
    r = Image.open(io.BytesIO(render_png)).convert("RGB").resize(photo.size)
    a, b = np.asarray(photo, np.float32), np.asarray(r, np.float32)
    mask = np.ones(a.shape[:2], bool)
    H, W = mask.shape
    for it in items:
        y0, x0, y1, x1 = it["box"]
        mask[int(y0 * H / 1000 * 0.9):int(min(1000, y1 * 1.05) * H / 1000),
             int(x0 * W / 1000 * 0.9):int(min(1000, x1 * 1.05) * W / 1000)] = False
    return round(float(np.abs(a - b).mean(2)[mask].mean()), 1)


def _score(checks: list[dict], drift: float, extras: list[str]) -> float:
    ious = [(c.get("iou") or 0.0) if c["found"] else 0.0 for c in checks if not c.get("rug")]
    return (sum(ious) / max(1, len(ious))) - max(0.0, drift - DRIFT_LIMIT) / 100 - 0.2 * len(extras)


def _feedback(checks: list[dict], drift: float, extras: list[str]) -> str:
    notes = []
    for c in checks:
        if not c["found"]:
            notes.append(f"product {c['n']} was missing")
        elif not c.get("rug") and c["iou"] < 0.5:
            notes.append(f"product {c['n']} was off its rectangle (width {c['width_error_pct']:+.0f}%, "
                         f"height {c['height_error_pct']:+.0f}%)")
    if drift > DRIFT_LIMIT:
        notes.append("the room itself was changed: keep everything outside the rectangles as in Image 1")
    for extra in extras:
        notes.append(f"remove {extra}: it isn't one of the numbered products or an approved styling touch")
    return ("Previous attempt problems: " + "; ".join(notes) + ". Fix them.") if notes else ""


# ---------------------------------------------------------------- whole run

def _public(result: dict) -> dict:
    """A placement without its numpy internals (for the trace)."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def run(room_id: str, job_id: str, brief: str, products: list[dict], on_stage=lambda stage, info=None: None) -> dict:
    """One restyle. Always leaves trace_<job>.json (inputs, design, placements, every attempt's checks, error)
    next to the images: the training and eval data for the reviewer model."""
    trace = {"job_id": job_id, "room_id": room_id, "brief": brief, "products": products,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "models": {"design": DESIGN_MODEL, "image": IMAGE_MODEL, "verify": FAST_MODEL}}
    try:
        summary = _run(room_id, job_id, brief, products, on_stage, trace)
        trace["status"] = "done"
        return summary
    except Exception as error:
        trace["status"], trace["error"] = "error", f"{type(error).__name__}: {error}"[:500]
        raise
    finally:
        try:
            storage.save(room_id, f"trace_{job_id}.json", json.dumps(trace, indent=1, default=str))
        except Exception:  # the trace is a by-product; never let it break the run's own outcome
            pass


def _run(room_id: str, job_id: str, brief: str, products: list[dict], on_stage, trace: dict) -> dict:
    t_start = time.perf_counter()
    folder: Path = storage.room_dir(room_id)
    photo_bytes = (folder / "photo.jpg").read_bytes()
    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    scene = json.loads((folder / "scene.json").read_text())
    cam = Camera(scene)
    room_cm = scene.get("room_cm")  # user-typed real dimensions, from POST /api/v1/rooms; optional
    timings = {}

    on_stage("context")
    t = time.perf_counter()
    products, needs = products_for_room(photo_bytes, brief, products)
    timings["context"] = round(time.perf_counter() - t, 1)

    on_stage("design")
    t = time.perf_counter()
    designed = design(photo_bytes, brief, products, needs, room_cm)
    timings["design"] = round(time.perf_counter() - t, 1)
    trace["design"] = designed
    plan, zones = designed["plan"], {z["id"]: z for z in designed["analysis"]["free_floor_zones"]}
    by_ref = {f"p{i}": p for i, p in enumerate(products, 1)}
    # Backup for the prompt instruction above (tweaks must not describe furniture): the prompt reduces
    # this, but can't guarantee it. A furniture-sounding tweak reaching render() gets drawn into the image
    # with no product behind it -- unlinked, unpriced, not really recommended -- which is worse than just
    # not showing it, so drop it here rather than trust the model followed the instruction.
    dropped_tweaks = [t for t in plan["tweaks"] if _mentions_furniture(t["instruction"])]
    if dropped_tweaks:
        log.warning("job %s: dropped furniture-like tweak(s) that aren't real picks: %s", job_id, dropped_tweaks)
    plan["tweaks"] = [t for t in plan["tweaks"] if t not in dropped_tweaks]
    # Full plan, not just the final placed items: without this, a pick that got dropped below (no
    # candidate of that category fit the zone) leaves no trace anywhere -- the summary only ever shows
    # what succeeded, so "why didn't X show up" was previously undiagnosable after the fact.
    log.info("design plan for job %s: needs=%s picks=%s tweaks=%s", job_id, needs, plan["picks"], plan["tweaks"])

    # Place each pick at true size; if it doesn't fit, try another search result of the same category.
    on_stage("place", {"vibe": plan["vibe"]})
    items, placed, used, rejected = [], {}, set(), []
    tried_trace = trace.setdefault("placements", [])
    for pick in plan["picks"]:
        product, zone = by_ref.get(pick["product_ref"]), zones.get(pick["zone_id"])
        if product is None or zone is None:
            tried_trace.append({"pick": pick, "ok": False, "why": "unknown product_ref or zone_id"})
            rejected.append({"pick": pick, "reason": "unknown product_ref or zone_id from the design plan"})
            continue
        same_kind = [p for p in products if p.get("category") == product.get("category") and p["id"] not in used]
        tried, placed_ok = [], False
        for candidate in [product, *[p for p in same_kind if p["id"] != product["id"]]][:4]:
            if candidate["id"] in used:
                continue
            result = place(pick, candidate, zone, cam, placed, room_cm)
            tried_trace.append({"pick": pick, "product_id": candidate["id"], **_public(result)})
            tried.append({"id": candidate["id"], "name": candidate["name"], "ok": result["ok"],
                          "why": result.get("why")})
            if result["ok"]:
                used.add(candidate["id"])
                placed[pick["id"]] = result
                items.append({"pick": pick, "product": candidate, **result})
                placed_ok = True
                break
        if not placed_ok:
            rejected.append({"pick": pick, "reason": "no candidate of this category fit the zone", "tried": tried})
    if rejected:
        log.warning("job %s: %d pick(s) never got placed: %s", job_id, len(rejected), rejected)
    if not items:
        raise RuntimeError("None of these products fits the empty floor in this photo. Try a photo with more floor.")

    guide = guide_image(photo, items)
    storage.save(room_id, f"guide_{job_id}.jpg", guide)
    on_stage("render", {"guide_url": storage.file_url(room_id, f"guide_{job_id}.jpg")})

    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(lambda it: fetch_product_image(it["product"].get("image_url")), items))
    refs = []
    for it, img in zip(items, images):
        it["ref_index"] = len(refs) if img else None
        if img:
            refs.append(img)

    attempts, feedback, pngs = [], "", {}
    trace["attempts"] = attempts
    for attempt in (1, 2):
        t = time.perf_counter()
        png = render(guide, items, refs, plan["tweaks"], plan["vibe"], _aspect(*photo.size), feedback)
        timings[f"render_{attempt}"] = round(time.perf_counter() - t, 1)
        pngs[attempt] = png
        storage.save(room_id, f"render_{job_id}_{attempt}.png", png)
        on_stage("verify", {"attempt": attempt})
        checks = verify(png, items)
        drift = room_drift(photo, png, items)
        extras = find_extras(png, items, plan["tweaks"])
        if extras:
            log.warning("job %s: render attempt %s added unrequested item(s): %s", job_id, attempt, extras)
        attempts.append({"attempt": attempt, "checks": checks, "drift": drift, "extras": extras,
                         "score": round(_score(checks, drift, extras), 3), "feedback_in": feedback})
        feedback = _feedback(checks, drift, extras)
        if not feedback:
            break
    best = max(attempts, key=lambda a: a["score"])
    trace["best_attempt"] = best["attempt"]
    storage.save(room_id, f"render_{job_id}.png", pngs[best["attempt"]])

    def card(p: dict) -> dict:
        return {"id": p["id"], "name": p["name"], "category": p.get("category"), "image_url": p.get("image_url"),
                "product_url": p.get("product_url"), "size_cm": _size_cm(p)}

    summary = {
        "room_id": room_id, "job_id": job_id, "brief": brief, "vibe": plan["vibe"],
        "photo_url": storage.file_url(room_id, "photo.jpg"),
        "guide_url": storage.file_url(room_id, f"guide_{job_id}.jpg"),
        "render_url": storage.file_url(room_id, f"render_{job_id}.png"),
        "items": [{
            "role": it["pick"]["role"], "product": card(it["product"]),
            # Where the piece is in the render (0-1000, [ymin, xmin, ymax, xmax]): where the AI drew it if
            # found, else where our true-size placement put it. Drives the numbered markers on the image.
            "box_2d": next((c["box_2d"] for c in best["checks"] if c["n"] == n and c.get("box_2d")), it["box"]),
            "placed_at_true_size": bool(next((c for c in best["checks"] if c["n"] == n and c["found"]
                                              and (c.get("rug") or (c["iou"] or 0) >= 0.5)), None)),
            "alternatives": [card(p) for p in products if p.get("category") == it["product"].get("category")
                             and p["id"] not in used][:3],
        } for n, it in enumerate(items, 1)],
        "styling": [t["instruction"] for t in plan["tweaks"]],
        "timings_s": {**timings, "total": round(time.perf_counter() - t_start, 1)},
        "attempts": [{k: a[k] for k in ("attempt", "drift", "score", "extras")} for a in attempts],
        "needs": needs,
        "rejected_picks": rejected,
        "room_cm": room_cm,
    }
    trace["timings_s"] = summary["timings_s"]
    storage.save(room_id, f"summary_{job_id}.json", json.dumps(summary, indent=2))
    on_stage("done")
    return summary
