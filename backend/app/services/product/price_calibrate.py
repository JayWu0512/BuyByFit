"""Measure the price estimates against real Amazon prices, then fix them.

    python -m app.services.product.price_calibrate --report     (from backend/; read-only accuracy report)
    python -m app.services.product.price_calibrate --apply      (real prices + recalibrated estimates -> DB)

Ground truth: amazon2023_prices.json (real Amazon prices for ABO ASINs, 2023). Then:
1. report: estimate vs real per product type (median ratio, % within the range, median abs. % error)
2. apply:
   - products with a real 2023 price: price = that price, price_source = 'amazon_reviews_2023',
     estimate cleared (the UI shows real prices as prices)
   - fit a log-price model on those real prices: log(price) = type base + size slope * log(size / typical)
     + material + brand effects (ridge least squares, so thin categories shrink toward the old rules)
   - re-estimate every product that still has no real price with the fitted model; range = the model's
     typical error band (25th-75th percentile of residuals), so the range means something
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url
from app.services.product.price_estimate import BRAND, MATERIAL, TYPICAL, DEFAULT, estimate, nice

TRUTH = Path.home() / "buybyfit-data" / "amazon2023_prices.json"
MODEL_VERSION = "est-v2-fitted"
FIELDS = ["id", "source_id", "product_type", "brand", "title", "material", "description",
          "width_cm", "depth_cm", "height_cm", "est_price_low", "est_price_high"]


def features(p: dict) -> dict:
    """Same inputs as the rule-based estimator, as model features."""
    ptype = (p.get("product_type") or "").upper()
    base, typical = TYPICAL.get(ptype, DEFAULT)
    dims = [float(d) for d in (p.get("width_cm"), p.get("depth_cm"), p.get("height_cm")) if d]
    if ptype == "RUG" and len(dims) >= 2:
        w, d = sorted(dims, reverse=True)[:2]
        log_size = math.log(max(w * d / (230 * 160), 0.05))
    else:
        log_size = math.log(max(max(dims) / typical, 0.05)) if dims else 0.0
    text = " ".join(str(p.get(k) or "") for k in ("material", "title", "description")).lower()
    brand_text = f"{p.get('brand') or ''} {p.get('title') or ''}".lower()
    mat = next((note for pat, _, note in MATERIAL if re.search(pat, text)), "none")
    brand = next((note or pat for pat, _, note in BRAND if re.search(pat, brand_text)), "other")
    m = re.search(r"set of (\d+)|(\d+)[- ]pack", (p.get("title") or "").lower())
    n = min(6, int(next(g for g in m.groups() if g))) if m else 1
    return {"type": ptype, "log_size": log_size, "material": mat, "brand": brand, "log_set": math.log(n),
            "sectional": float(ptype == "SOFA" and bool(re.search(r"sectional|[lu]-shaped", text)))}


class PriceModel:
    """log(price) = sum of one-hot effects (type, material, brand) + slopes; ridge-regularised."""

    def __init__(self, ridge: float = 2.0):
        self.ridge = ridge

    def _design(self, rows, fit=False):
        if fit:
            self.levels = {k: sorted({r[k] for r in rows}) for k in ("type", "material", "brand")}
            self.cols = [f"{k}={v}" for k in self.levels for v in self.levels[k]] + ["log_size", "log_set", "sectional"]
        X = np.zeros((len(rows), len(self.cols)))
        idx = {c: i for i, c in enumerate(self.cols)}
        for i, r in enumerate(rows):
            for k in ("type", "material", "brand"):
                j = idx.get(f"{k}={r[k]}")
                if j is not None:
                    X[i, j] = 1
            X[i, idx["log_size"]], X[i, idx["log_set"]], X[i, idx["sectional"]] = r["log_size"], r["log_set"], r["sectional"]
        return X

    def fit(self, rows, y):
        X = self._design(rows, fit=True)
        self.mu = float(np.mean(y))
        A = X.T @ X + self.ridge * np.eye(X.shape[1])
        self.w = np.linalg.solve(A, X.T @ (np.asarray(y) - self.mu))
        resid = np.asarray(y) - self.predict_log(rows)
        self.band = (float(np.percentile(resid, 25)), float(np.percentile(resid, 75)))
        return self

    def predict_log(self, rows):
        return self.mu + self._design(rows) @ self.w


TRUTH_2018 = Path.home() / "buybyfit-data" / "amazon2018_prices.json"


def load():
    """Real prices: 2023 edition first, 2018 edition otherwise (ABO items were on sale around 2018-19)."""
    truth = {}
    for f, year in ((TRUTH_2018, 2018), (TRUTH, 2023)):        # later wins
        if f.exists():
            for asin, v in json.loads(f.read_text(encoding="utf-8")).items():
                if v.get("price"):
                    truth[asin] = {**v, "year": year}
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    with conn, conn.cursor() as cur:
        cur.execute(f"select {', '.join(FIELDS)} from products where source = 'abo'")
        products = [dict(zip(FIELDS, r)) for r in cur.fetchall()]
    conn.close()
    for p in products:
        t = truth.get(p["source_id"])
        p["real"] = t["price"] if t else None
        p["real_year"] = t["year"] if t else None
    return products


def report(products):
    by_type = defaultdict(list)
    for p in products:
        if p["real"] and p["est_price_low"] is not None:
            lo, hi = float(p["est_price_low"]), float(p["est_price_high"])
            by_type[p["product_type"]].append((p["real"], lo, hi))
    allrows = [r for v in by_type.values() for r in v]
    print(f"products with a real 2023 price: {len(allrows)}\n")
    print(f"{'type':<26}{'n':>5}{'median est/real':>17}{'within range':>14}{'median |err|':>14}")
    for t, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])) + [("ALL", allrows)]:
        if len(rows) < 5 and t != "ALL":
            continue
        ratio = np.median([((lo + hi) / 2) / real for real, lo, hi in rows])
        inside = np.mean([lo <= real <= hi for real, lo, hi in rows])
        err = np.median([abs((lo + hi) / 2 - real) / real for real, lo, hi in rows])
        print(f"{t:<26}{len(rows):>5}{ratio:>16.2f}x{inside:>13.0%}{err:>13.0%}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    products = load()
    print("== current (rule-based) estimates vs real Amazon prices")
    report(products)

    train = [p for p in products if p["real"]]
    feats = [features(p) for p in train]
    y = [math.log(p["real"]) for p in train]
    # honest error: 5-fold cross-validation (predict each product with a model that never saw it)
    rng = np.random.default_rng(0)
    folds = rng.integers(0, 5, len(train))
    preds = np.zeros(len(train))
    for k in range(5):
        tr, te = folds != k, folds == k
        m = PriceModel().fit([f for f, keep in zip(feats, tr) if keep], np.asarray(y)[tr])
        preds[te] = m.predict_log([f for f, keep in zip(feats, te) if keep])
    err = np.abs(np.exp(preds) - np.exp(y)) / np.exp(y)
    lo_b, hi_b = PriceModel().fit(feats, y).band
    inside = np.mean([(math.exp(p + lo_b) <= math.exp(t) <= math.exp(p + hi_b)) for p, t in zip(preds, y)])
    print(f"\n== fitted model, 5-fold cross-validated on {len(train)} real prices")
    print(f"median |error| {np.median(err):.0%} · within the shown range {inside:.0%} (range = middle 50% of errors)")
    if not args.apply:
        return 0

    model = PriceModel().fit(feats, y)
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, "update products p set price = v.price, currency = 'USD', price_source = v.src, "
                                "price_status = 'historical', est_price_low = null, est_price_high = null, est_price_basis = null "
                                "from (values %s) as v(id, price, src) where p.id = v.id",
                           [(p["id"], round(p["real"], 2), f"amazon_reviews_{p['real_year']}") for p in train],
                           template="(%s, %s::numeric, %s)")
            rest = [p for p in products if not p["real"]]
            logp = model.predict_log([features(p) for p in rest])
            rows = []
            for p, lp in zip(rest, logp):
                lo, hi = nice(math.exp(lp + model.band[0])), nice(math.exp(lp + model.band[1]))
                old = estimate(p)
                basis = (old[2] if old else "") + " · fitted on real Amazon prices"
                rows.append((p["id"], lo, max(hi, lo + 5), basis, MODEL_VERSION))
            execute_values(cur, "update products p set est_price_low = v.lo, est_price_high = v.hi, est_price_basis = v.basis, "
                                "est_price_model = v.m from (values %s) as v(id, lo, hi, basis, m) where p.id = v.id",
                           rows, template="(%s, %s::numeric, %s::numeric, %s, %s)", page_size=1000)
        print(f"\nset {len(train)} real prices; re-estimated {len(rows)} products with {MODEL_VERSION}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
