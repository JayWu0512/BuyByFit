"""Price estimates anchored on IKEA's real prices, scaled to Amazon's brands with real Amazon prices.

    python -m app.services.product.price_model_ikea --report          (from backend/; read-only)
    python -m app.services.product.price_model_ikea --apply
    python -m app.services.product.price_model_ikea --sheet           (writes the manual price-check sheet)

Why: only ~43 real Amazon prices exist for our products, too few to learn how price depends on type and size.
IKEA's US catalogue has thousands of real prices with sizes, so:
1. IKEA model: log(price) = type base + type-specific size slope * log(size / typical) + material effects,
   ridge-fitted on IKEA's real prices. IKEA sofas/armchairs list no size, so their size comes from the
   category (loveseat ~160 cm, three-seat ~220 cm, with chaise ~250 cm).
2. Brand multiplier: log(amazon real) - log(IKEA model) averaged per price tier (budget / mid / premium),
   ridge-shrunk to the global average, from the real Amazon prices (plus any manual checks, below).
3. Estimate = IKEA model x tier multiplier; the shown range is the 20th-80th percentile of leave-one-out errors.
Types IKEA doesn't sell keep their current calibrated estimate.

Manual checks: ~/buybyfit-data/price_check_sheet.csv (from --sheet). Fill `real_price_usd` by opening each
product page in a browser; filled rows are used as real prices (price_source = 'manual_check') and to fit.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

from app.services.product import ikea_import
from app.services.product.index_products import database_url
from app.services.product.price_estimate import MATERIAL, nice

DATA = Path.home() / "buybyfit-data"
TRUTH_2023 = DATA / "amazon2023_prices.json"
SHEET = DATA / "price_check_sheet.csv"
MODEL_VERSION = "est-v3-ikea-anchored"

EXTRA_CATEGORIES = {"art-posters-and-prints": "WALL_ART", "frames": "WALL_ART", "headboards": "HEADBOARD",
                    "ceiling-lamps": "LIGHT_FIXTURE", "sofa-beds": "SOFA", "two-seat-sofas": "SOFA",
                    "accent-tables": "TABLE", "dining-tables": "TABLE", "kitchen-and-dining-tables": "TABLE",
                    "storage-ottomans": "OTTOMAN", "bed-frames-with-storage": "BED"}
# implicit size (cm, largest side) for IKEA categories that list none
CATEGORY_SIZE = {"loveseats": 160, "three-seat-sofas": 220, "sofas-with-chaise": 250, "sofa-beds": 200,
                 "two-seat-sofas": 170, "fabric-armchairs": 85, "leather-armchairs": 85, "rattan-armchairs": 80,
                 "dining-chairs": 55, "office-chairs": 65, "desk-chairs-for-home": 65, "folding-chairs": 50,
                 "kids-armchairs": 55, "bed-frames": 210, "upholstered-beds": 215, "bed-frames-with-storage": 210}
TYPICAL = {"SOFA": 210, "CHAIR": 80, "TABLE": 110, "DESK": 120, "BED": 210, "SHELF": 170, "DRESSER": 110,
           "CABINET": 110, "OTTOMAN": 70, "BENCH": 115, "STOOL_SEATING": 75, "LAMP": 150, "LIGHT_FIXTURE": 50,
           "RUG": 230, "PLANTER": 30, "VASE": 30, "PILLOW": 45, "HOME_MIRROR": 80, "CLOCK": 35, "BASKET": 40,
           "PLUSH_TOY": 35, "ARTIFICIAL_PLANT": 120, "WALL_ART": 70, "HEADBOARD": 160,
           "HOME_FURNITURE_AND_DECOR": 100}
MAT_KEYS = ["leather", "stone", "solid wood", "velvet", "natural fibre", "faux leather", "engineered wood/plastic"]


def material(text: str) -> str:
    return next((note for pat, _, note in MATERIAL if re.search(pat, (text or "").lower())), "none")


def size_of(p: dict, folder: str | None = None) -> float | None:
    dims = [float(d) for d in (p.get("width_cm"), p.get("depth_cm"), p.get("height_cm")) if d and float(d) > 2]
    if p["product_type"] == "RUG" and len(dims) >= 2:
        w, d = sorted(dims, reverse=True)[:2]
        return math.sqrt(w * d)            # rugs: geometric mean side, so area drives price
    if dims:
        return max(dims)
    return CATEGORY_SIZE.get(folder) if folder else None


class Model:
    """log(price) ~ type + type*log(size/typical) + material; ridge on everything except the type intercepts."""

    def fit(self, rows, y, ridge=1.0):
        self.types = sorted({r["type"] for r in rows})
        self.cols = [f"t={t}" for t in self.types] + [f"s={t}" for t in self.types] + [f"m={m}" for m in MAT_KEYS]
        X = self._x(rows)
        pen = np.array([0.01 if c.startswith("t=") else ridge for c in self.cols])
        self.w = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ np.asarray(y))
        return self

    def _x(self, rows):
        idx = {c: i for i, c in enumerate(self.cols)}
        X = np.zeros((len(rows), len(self.cols)))
        for i, r in enumerate(rows):
            if f"t={r['type']}" in idx:
                X[i, idx[f"t={r['type']}"]] = 1
                X[i, idx[f"s={r['type']}"]] = r["log_size"]
            if f"m={r['mat']}" in idx:
                X[i, idx[f"m={r['mat']}"]] = 1
        return X

    def knows(self, ptype):
        return ptype in self.types

    def predict(self, rows):
        return self._x(rows) @ self.w


def row(p, folder=None):
    s = size_of(p, folder)
    t = p["product_type"]
    return {"type": t, "mat": material(f"{p.get('material') or ''} {p.get('title') or ''}"),
            "log_size": math.log(max(s / TYPICAL.get(t, 100), 0.05)) if s else 0.0}


def ikea_training():
    cats = {**ikea_import.CATEGORY_TYPES, **EXTRA_CATEGORIES}
    ikea_import.CATEGORY_TYPES.update(EXTRA_CATEGORIES)
    products = ikea_import.load(list(cats))
    rows, y = [], []
    for p in products:
        folder = re.sub(r"[^a-z0-9-]", "", (p["category"][-1] or "").lower().replace(" ", "-").replace("&", "and"))
        folder = next((f for f in cats if cats[f] == p["product_type"] and f.replace("-", " ") in p["category"][-1].lower()), folder)
        if p.get("price") and 1 < p["price"] < 10_000:
            rows.append(row(p, folder))
            y.append(math.log(p["price"]))
    return rows, np.array(y), Counter(r["type"] for r in rows)


def manual_prices() -> dict[str, float]:
    if not SHEET.exists():
        return {}
    out = {}
    with SHEET.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = (r.get("real_price_usd") or "").replace("$", "").replace(",", "").strip()
            if v:
                try:
                    out[r["id"]] = float(v)
                except ValueError:
                    pass
    return out


def load_catalogue():
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    with conn, conn.cursor() as cur:
        cur.execute("select id, source_id, product_type, title, brand, material, width_cm, depth_cm, height_cm, "
                    "price, price_source, price_tier, url, est_price_low, est_price_high from products")
        cols = [d[0] for d in cur.description]
        products = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return products


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    args = ap.parse_args(argv)
    products = load_catalogue()

    if args.sheet:
        rng = np.random.default_rng(1)
        pool = [p for p in products if p["price"] is None and p["url"] and "amazon.com/" in p["url"]]
        picked, seen = [], Counter()
        for p in sorted(pool, key=lambda _: rng.random()):
            key = (p["product_type"], p["price_tier"])
            if p["product_type"] in ("SOFA", "CHAIR", "LAMP", "BED", "RUG", "TABLE", "OTTOMAN", "DRESSER") and seen[key] < 2:
                picked.append(p)
                seen[key] += 1
            if len(picked) >= 40:
                break
        with SHEET.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "type", "tier", "title", "url", "current_estimate", "real_price_usd"])
            for p in picked:
                est = f"${p['est_price_low']:.0f}-{p['est_price_high']:.0f}" if p["est_price_low"] else ""
                w.writerow([p["id"], p["product_type"], p["price_tier"], p["title"][:90], p["url"], est, ""])
        print(f"wrote {len(picked)} products to {SHEET}")
        return 0

    rows, y, per_type = ikea_training()
    print(f"IKEA training prices: {len(rows)}; per type: {dict(per_type.most_common())}")
    ikea = Model().fit(rows, y)

    truth = json.loads(TRUTH_2023.read_text(encoding="utf-8")) if TRUTH_2023.exists() else {}
    manual = manual_prices()
    train = []
    for p in products:
        real = manual.get(p["id"])
        if real is None and p["price_source"] == "amazon_reviews_2023":
            real = float(p["price"])
        if real and ikea.knows(p["product_type"]):
            train.append((p, real))
    print(f"real Amazon prices to learn the brand multiplier: {len(train)} (manual checks: {len(manual)})")
    tiers = ["budget", "mid", "premium", "none"]
    base = ikea.predict([row(p) for p, _ in train])
    resid = np.array([math.log(real) for _, real in train]) - base

    def fit_mult(idx):
        # global + per-tier offsets, ridge-shrunk
        g = resid[idx].mean() if len(idx) else 0.0
        out = {"global": g}
        for t in tiers:
            sel = [i for i in idx if (train[i][0]["price_tier"] or "none") == t]
            out[t] = (resid[sel] - g).sum() / (len(sel) + 3.0) if sel else 0.0
        return out

    loo = []
    for i in range(len(train)):
        m = fit_mult([j for j in range(len(train)) if j != i])
        loo.append(base[i] + m["global"] + m[train[i][0]["price_tier"] or "none"])
    loo = np.array(loo)
    err = np.array([math.log(real) for _, real in train]) - loo
    lo_q, hi_q = np.percentile(err, 20), np.percentile(err, 80)
    med = np.median(np.abs(np.exp(-err) - 1))
    inside = np.mean((err >= lo_q) & (err <= hi_q))
    cur_err = [abs(((float(p["est_price_low"]) + float(p["est_price_high"])) / 2) / real - 1)
               for p, real in train if p["est_price_low"]]
    mult = fit_mult(list(range(len(train))))
    print(f"\ncurrent estimates (v2):  median error {np.median(cur_err):.0%}" if cur_err else "")
    print(f"IKEA-anchored (v3):      median error {med:.0%} (leave-one-out) · range holds the real price {inside:.0%}")
    print("Amazon brand vs IKEA multiplier:", {k: round(math.exp(mult['global'] + (mult[k] if k != 'global' else 0)), 2)
                                                 for k in ["budget", "mid", "premium", "none"]})
    if not args.apply:
        return 0

    todo = [p for p in products if p["price"] is None and ikea.knows(p["product_type"]) and p["id"] not in manual]
    pred = ikea.predict([row(p) for p in todo])
    rows_out = []
    for p, lp in zip(todo, pred):
        mid = lp + mult["global"] + mult[p["price_tier"] or "none"]
        lo, hi = nice(math.exp(mid + lo_q)), nice(math.exp(mid + hi_q))
        basis = f"{p['product_type'].lower().replace('_', ' ')} · priced like IKEA x Amazon {p['price_tier'] or 'other'} brand level"
        rows_out.append((p["id"], lo, max(hi, lo + 5), basis, MODEL_VERSION))
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, "update products p set est_price_low = v.lo, est_price_high = v.hi, est_price_basis = v.b, "
                                "est_price_model = v.m from (values %s) as v(id, lo, hi, b, m) where p.id = v.id",
                           rows_out, template="(%s, %s::numeric, %s::numeric, %s, %s)", page_size=1000)
            if manual:
                execute_values(cur, "update products p set price = v.price, currency = 'USD', price_source = 'manual_check', "
                                    "price_status = 'checked', price_checked_at = now(), est_price_low = null, "
                                    "est_price_high = null, est_price_basis = null from (values %s) as v(id, price) "
                                    "where p.id = v.id", list(manual.items()), template="(%s, %s::numeric)")
        print(f"re-estimated {len(rows_out)} products ({MODEL_VERSION}); manual prices applied: {len(manual)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
