"""Impute a price range for every product without a real price, calibrated on real Amazon prices.

    python -m app.services.product.price_impute --report     (from backend/; read-only)
    python -m app.services.product.price_impute --apply

Model: start from the rule-based estimate (price_estimate.estimate: type x size x material x brand), then
correct it with a few factors learned from real prices:  log(real) = log(rule) + global + tier + group,
fitted by ridge regression on the real 2023 Amazon prices (2018 prices are excluded: they proved wrong,
e.g. a $4.64 office chair). Ridge shrinks each correction toward 0 (= trust the rule) when data is thin.

Accuracy is measured leave-one-out and printed next to the old rule. The shown range comes from the
leave-one-out errors (20th-80th percentile), so "Est. $X-$Y" contains the real price about 60% of the time.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url
from app.services.product.price_estimate import estimate, nice

TRUTH = Path.home() / "buybyfit-data" / "amazon2023_prices.json"
MODEL_VERSION = "est-v2-calibrated"
GROUPS = {
    "seating": {"SOFA", "CHAIR", "STOOL_SEATING", "OTTOMAN", "BENCH", "BEAN_BAG_CHAIR"},
    "tables": {"TABLE", "DESK"},
    "storage": {"SHELF", "CABINET", "DRESSER", "HOME_FURNITURE_AND_DECOR", "BASKET"},
    "beds": {"BED", "BED_FRAME", "HEADBOARD", "MATTRESS"},
    "lighting": {"LAMP", "LIGHT_FIXTURE"},
    "decor": {"WALL_ART", "HOME_MIRROR", "CLOCK", "VASE", "PLANTER", "PILLOW", "CANDLE_HOLDER", "FIGURINE",
              "SCULPTURE", "ARTIFICIAL_PLANT", "PLUSH_TOY", "DECOR"},
    "rugs": {"RUG"},
}
FIELDS = ["id", "source_id", "product_type", "brand", "title", "material", "description",
          "width_cm", "depth_cm", "height_cm", "price", "price_source", "price_tier"]


def group(ptype: str) -> str:
    return next((g for g, types in GROUPS.items() if ptype in types), "other")


def design(rows: list[dict], cols: list[str]) -> np.ndarray:
    X = np.zeros((len(rows), len(cols)))
    idx = {c: i for i, c in enumerate(cols)}
    for i, p in enumerate(rows):
        X[i, idx["global"]] = 1
        for key in (f"tier={p.get('price_tier') or 'none'}", f"group={group(p['product_type'] or '')}"):
            if key in idx:
                X[i, idx[key]] = 1
    return X


def fit(X: np.ndarray, y: np.ndarray, ridge: float = 3.0) -> np.ndarray:
    return np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)


def load():
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    with conn, conn.cursor() as cur:
        cur.execute(f"select {', '.join(FIELDS)} from products")
        products = [dict(zip(FIELDS, r)) for r in cur.fetchall()]
    conn.close()
    for p in products:
        est = estimate(p)
        p["rule"] = (est[0] + est[1]) / 2 if est else None
        p["basis"] = est[2] if est else None
        t = truth.get(p["source_id"]) if p["price_source"] == "amazon_reviews_2023" else None
        p["real"] = float(t["price"]) if t and t.get("price") else None
    return products


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    products = load()
    train = [p for p in products if p["real"] and p["rule"]]
    cols = ["global"] + [f"tier={t}" for t in ("budget", "mid", "premium", "none")] + [f"group={g}" for g in GROUPS] + ["group=other"]
    X, y = design(train, cols), np.array([math.log(p["real"] / p["rule"]) for p in train])

    # leave-one-out: each real price predicted by a model that never saw it
    loo = np.array([design([train[i]], cols) @ fit(np.delete(X, i, 0), np.delete(y, i)) for i in range(len(train))]).ravel()
    resid = y - loo
    lo_q, hi_q = np.percentile(resid, 20), np.percentile(resid, 80)
    rule_err = np.median(np.abs(np.exp(-y) - 1))           # rule/real - 1
    cal_err = np.median(np.abs(np.exp(loo - y) - 1))
    inside = np.mean((resid >= lo_q) & (resid <= hi_q))
    print(f"real 2023 prices used: {len(train)}")
    print(f"old rule:       median error {rule_err:.0%}")
    print(f"calibrated:     median error {cal_err:.0%}  (leave-one-out) · range holds the real price {inside:.0%} of the time")
    w = fit(X, y)
    print("learned corrections (x price):", {c: round(math.exp(v), 2) for c, v in zip(cols, w) if abs(v) > 0.02})
    if not args.apply:
        return 0

    todo = [p for p in products if p["price"] is None and p["rule"]]
    corr = design(todo, cols) @ w
    rows = []
    for p, c in zip(todo, corr):
        mid = p["rule"] * math.exp(c)
        lo, hi = nice(mid * math.exp(lo_q)), nice(mid * math.exp(hi_q))
        rows.append((p["id"], lo, max(hi, lo + 5), f"{p['basis']} · calibrated on {len(train)} real Amazon prices",
                     MODEL_VERSION))
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, "update products p set est_price_low = v.lo, est_price_high = v.hi, est_price_basis = v.b, "
                                "est_price_model = v.m from (values %s) as v(id, lo, hi, b, m) where p.id = v.id",
                           rows, template="(%s, %s::numeric, %s::numeric, %s, %s)", page_size=1000)
        print(f"imputed {len(rows)} products ({MODEL_VERSION})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
