"""Estimated price ranges for catalogue products that have no real price (all of ABO and Objaverse).

    python -m app.services.product.price_estimate            (from backend/; writes to the DB)
    python -m app.services.product.price_estimate --dry-run  (prints a sample)

The estimate is a typical-price model, not a quote:
    typical price for the product type (at a typical size)
    x size        (largest dimension vs typical, ^0.8: bigger costs more, but less than linearly)
    x material    (top-grain leather, solid wood, marble > fabric > MDF / plastic)
    x brand tier  (Stone & Beam > Rivet > Ravenna > Movian / Alkove > Solimo / AmazonBasics)
and shown as a range (-20% / +25%), rounded to friendly numbers, always labelled as an estimate.

Results go to est_price_low / est_price_high / est_price_basis. `price` stays reserved for real prices.
"""
from __future__ import annotations

import argparse
import math
import re

import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url

MODEL_VERSION = "est-v1"

# product_type: (typical USD price, typical largest dimension in cm)
TYPICAL = {
    "SOFA": (750, 210), "CHAIR": (280, 90), "TABLE": (220, 110), "DESK": (260, 120), "BED": (700, 210),
    "BED_FRAME": (260, 205), "HEADBOARD": (230, 160), "MATTRESS": (420, 200), "OTTOMAN": (150, 75),
    "BENCH": (190, 115), "STOOL_SEATING": (110, 75), "SHELF": (150, 170), "CABINET": (320, 110),
    "DRESSER": (460, 120), "HOME_FURNITURE_AND_DECOR": (210, 110), "RUG": (170, 230), "LAMP": (90, 150),
    "LIGHT_FIXTURE": (120, 55), "PILLOW": (30, 45), "PLANTER": (40, 35), "VASE": (35, 30),
    "BEAN_BAG_CHAIR": (120, 95), "CANDLE_HOLDER": (25, 25), "FIGURINE": (35, 25), "SCULPTURE": (55, 35),
    "ARTIFICIAL_PLANT": (45, 60), "BASKET": (35, 40), "CLOCK": (45, 40), "HOME_MIRROR": (130, 80),
    "WALL_ART": (90, 80), "PLUSH_TOY": (22, 30), "DECOR": (25, 18),
}
DEFAULT = (120, 80)

MATERIAL = [  # first match wins
    (r"top[- ]grain|full[- ]grain|genuine leather|(?<!faux )(?<!vegan )leather(?!ette)", 1.35, "leather"),
    (r"marble|travertine|granite", 1.25, "stone"),
    (r"solid (wood|oak|walnut|acacia|mango|teak|pine)|walnut|oak|teak|acacia|mango wood", 1.2, "solid wood"),
    (r"velvet", 1.1, "velvet"),
    (r"rattan|wicker|jute|seagrass", 1.05, "natural fibre"),
    (r"faux leather|leatherette|vegan leather|bonded leather|pu\b|polyurethane", 0.9, "faux leather"),
    (r"particle ?board|mdf|engineered wood|laminate|plastic|polypropylene|resin", 0.8, "engineered wood/plastic"),
]
BRAND = [
    (r"stone ?& ?beam", 1.15, "Stone & Beam"), (r"rivet", 1.0, "Rivet"), (r"ravenna", 0.95, "Ravenna Home"),
    (r"movian|alkove|alveare", 0.85, None), (r"solimo", 0.75, "Solimo"), (r"amazon ?basics|amazon basics", 0.7, "AmazonBasics"),
]


def nice(x: float) -> int:
    """Round to a number a shop would print."""
    if x < 30:
        return max(5, int(round(x)))
    step = 5 if x < 100 else 10 if x < 500 else 25 if x < 1500 else 50
    return int(round(x / step) * step)


def estimate(p: dict) -> tuple[int, int, str] | None:
    ptype = (p.get("product_type") or "").upper()
    base, typical = TYPICAL.get(ptype, DEFAULT)
    dims = [d for d in (p.get("width_cm"), p.get("depth_cm"), p.get("height_cm")) if d]
    text = " ".join(str(p.get(k) or "") for k in ("material", "title", "description")).lower()
    brand_text = f"{p.get('brand') or ''} {p.get('title') or ''}".lower()

    if ptype == "RUG" and len(dims) >= 2:                          # rugs price by area
        w, d = sorted(dims, reverse=True)[:2]
        size = (w * d / (230 * 160)) ** 0.85
        size_note = f"{w / 100:.1f} × {d / 100:.1f} m"
    elif dims:
        size = (max(dims) / typical) ** 0.8
        size_note = f"{max(dims):.0f} cm"
    else:
        size, size_note = 1.0, "typical size"
    size = min(max(size, 0.45), 2.8)

    mat, mat_note = 1.0, None
    for pat, f, note in MATERIAL:
        if re.search(pat, text):
            mat, mat_note = f, note
            break
    brand, brand_note = 1.0, None
    for pat, f, note in BRAND:
        if re.search(pat, brand_text):
            brand, brand_note = f, note
            break

    extra, extra_notes = 1.0, []
    title = (p.get("title") or "").lower()
    if m := re.search(r"set of (\d+)|(\d+)[- ]pack|(\d+)[- ]piece", title):
        n = min(6, int(next(g for g in m.groups() if g)))
        if n > 1:
            extra *= n ** 0.9
            extra_notes.append(f"set of {n}")
    if ptype == "SOFA" and re.search(r"sectional|[lu]-shaped|\b[lu]-sec", title):
        extra *= 1.35
        extra_notes.append("sectional")
    if ptype == "RUG" and re.search(r"\bwool\b|hand[- ]?(knotted|tufted|woven)", text):
        extra *= 1.25
        extra_notes.append("wool/handmade")

    mid = base * size * mat * brand * extra
    low, high = nice(mid * 0.8), nice(mid * 1.25)
    if high <= low:
        high = nice(low * 1.3) if low >= 10 else low + 5
    kind = ptype.replace("_", " ").lower() or "item"
    basis = " · ".join(x for x in [kind, *extra_notes, size_note, mat_note, brand_note] if x)
    return low, high, basis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("alter table products add column if not exists est_price_low numeric, "
                        "add column if not exists est_price_high numeric, add column if not exists est_price_basis text, "
                        "add column if not exists est_price_model text")
            cur.execute("select id, product_type, brand, title, material, description, width_cm, depth_cm, height_cm "
                        "from products where price is null")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            out = [(r["id"], *est, MODEL_VERSION) for r in rows if (est := estimate(r))]
            if args.dry_run:
                for (pid, lo, hi, basis, _), r in list(zip(out, rows))[:: max(1, len(out) // 25)]:
                    print(f"  ${lo:>5}–{hi:<5} {basis:<45} {r['title'][:55]}")
                conn.rollback()
                return 0
            execute_values(cur,
                "update products p set est_price_low = v.lo, est_price_high = v.hi, est_price_basis = v.basis, "
                "est_price_model = v.model from (values %s) as v(id, lo, hi, basis, model) where p.id = v.id",
                out, template="(%s, %s::numeric, %s::numeric, %s, %s)", page_size=1000)
            print(f"estimated {len(out)} of {len(rows)} unpriced products ({MODEL_VERSION})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
