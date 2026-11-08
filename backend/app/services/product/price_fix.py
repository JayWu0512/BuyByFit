"""Replace the uncalibrated price estimates with what we can actually stand behind.

    python -m app.services.product.price_fix                       (from backend/; real prices + tiers)
    python -m app.services.product.price_fix --clear-estimates     (also wipes all estimates; then re-run
                                                                    price_impute.py --apply)

Checked against 48 real Amazon prices (price_calibrate.py --report), the rule-based estimates were off by a
median ~45% (chairs ~3x too high) and the range held the real price only 31% of the time; 48 points are too
few to fit a better model. So:
1. real prices where we have them: Amazon Reviews 2023 / 2018 item metadata (historical list prices),
   price_source = amazon_reviews_<year>, price_status = 'historical'. Never overwrites a price someone else set.
2. clear every estimate (est_price_low / high / basis / model), so nothing shows a made-up number
3. price_tier = budget / mid / premium from the brand line (AmazonBasics, Solimo < Rivet, Ravenna, Movian,
   Alkove < Stone & Beam), for coarse budget filtering without pretending to know the price
"""
from __future__ import annotations

import json
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from app.services.product.index_products import database_url

DATA = Path.home() / "buybyfit-data"
TIERS = [  # (SQL regex on brand/title, tier); first match wins
    (r"amazon ?basics|solimo", "budget"),
    (r"stone ?& ?beam", "premium"),
    (r"rivet|ravenna|movian|alkove|strathwood|phoenix home|red hook", "mid"),
]


def real_prices() -> dict[str, tuple[float, int]]:
    out = {}
    # 2023 only: the 2018 edition's prices proved wrong for these products (e.g. a $4.64 office chair)
    for name, year in (("amazon2023_prices.json", 2023),):
        f = DATA / name
        if f.exists():
            for asin, v in json.loads(f.read_text(encoding="utf-8")).items():
                if v.get("price"):
                    out[asin] = (round(float(v["price"]), 2), year)
    return out


def main() -> int:
    import sys
    clear = "--clear-estimates" in sys.argv     # off by default: price_impute.py writes the calibrated estimates
    prices = real_prices()
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("alter table products add column if not exists price_tier text")
            execute_values(
                cur,
                "update products p set price = v.price, currency = 'USD', price_source = v.src, "
                "price_status = 'historical', price_checked_at = now() "
                "from (values %s) as v(asin, price, src) "
                "where p.source = 'abo' and p.source_id = v.asin and p.price is null",
                [(a, p, f"amazon_reviews_{y}") for a, (p, y) in prices.items()],
                template="(%s, %s::numeric, %s)")
            print(f"real prices written: {cur.rowcount} (of {len(prices)} found)")
            if clear:
                cur.execute("update products set est_price_low = null, est_price_high = null, "
                            "est_price_basis = null, est_price_model = null where est_price_low is not null")
                print(f"estimates cleared: {cur.rowcount}")
            cur.execute("update products set price_tier = null")
            for pattern, tier in TIERS:
                cur.execute("update products set price_tier = %s where price_tier is null and "
                            "(coalesce(brand, '') || ' ' || title) ~* %s", (tier, pattern))
            cur.execute("select coalesce(price_tier, '(none)'), count(*) from products group by 1 order by 2 desc")
            print("price tiers:", dict(cur.fetchall()))
            cur.execute("select count(*) filter (where price is not null), count(*) filter (where est_price_low is not null) "
                        "from products")
            print("now: products with a real price = %s, with an estimate = %s" % cur.fetchone())
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
