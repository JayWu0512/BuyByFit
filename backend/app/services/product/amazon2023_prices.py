"""Real Amazon prices for ABO products, from the Amazon Reviews 2023 item metadata (McAuley lab, UCSD).

    python -m app.services.product.amazon2023_prices            (from backend/; ~12 GB streamed, nothing stored)

ABO item ids are Amazon ASINs. meta_Home_and_Kitchen.jsonl (3.7M items, prices as listed in 2023) is
streamed line by line over HTTP; only items whose ASIN matches one of ours are kept, in
~/buybyfit-data/amazon2023_prices.json -> {asin: {"price": 249.99, "title": ..., "store": ...}}.
The dataset's licence is unclear (the maintainers don't assign one), so treat it as research use.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import psycopg2

from app.services.product.index_products import database_url

URL = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/{}.jsonl"
FILES = ["meta_Home_and_Kitchen"]
OUT = Path.home() / "buybyfit-data" / "amazon2023_prices.json"


def our_asins() -> set[str]:
    conn = psycopg2.connect(database_url(), connect_timeout=20)
    with conn, conn.cursor() as cur:
        cur.execute("select source_id from products where source = 'abo'")
        ids = {r[0] for r in cur.fetchall()}
    conn.close()
    return ids


def parse_price(v):
    if v is None:
        return None
    try:
        p = float(str(v).replace("$", "").replace(",", "").strip())
        return p if 0 < p < 50_000 else None
    except ValueError:
        return None


URL_2018 = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_v2/metaFiles2/meta_Home_and_Kitchen.json.gz"
OUT_2018 = Path.home() / "buybyfit-data" / "amazon2018_prices.json"


def main_2018() -> int:
    """Same idea on the 2018 edition (gzip, field 'asin', price like '$249.99'): these ABO items were
    still on sale around 2018-2019, so far more of them have a price there."""
    import gzip
    wanted = our_asins()
    found = {}
    req = urllib.request.Request(URL_2018, headers={"User-Agent": "BuyByFit-student-project/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, gzip.open(r, "rt", encoding="utf-8", errors="replace") as lines:
        for i, line in enumerate(lines, 1):
            k = line.find('"asin": "')
            asin = line[k + 9:k + 19] if k >= 0 else None
            if asin in wanted:
                item = json.loads(line)
                found[asin] = {"price": parse_price(item.get("price")), "title": item.get("title"),
                               "brand": item.get("brand")}
            if i % 250_000 == 0:
                print(f"  2018: {i:,} lines, {len(found)} matches, {sum(1 for v in found.values() if v['price'])} priced",
                      flush=True)
    OUT_2018.write_text(json.dumps(found), encoding="utf-8")
    print(f"2018: matched {len(found)}; {sum(1 for v in found.values() if v['price'])} have a price -> {OUT_2018}")
    return 0


def main() -> int:
    if "--2018" in sys.argv:
        return main_2018()
    from huggingface_hub import get_token
    wanted = our_asins()
    print(f"looking for {len(wanted)} ABO ASINs", flush=True)
    found: dict[str, dict] = {}
    headers = {"User-Agent": "BuyByFit-student-project/1.0"}
    if get_token():
        headers["Authorization"] = f"Bearer {get_token()}"
    for name in FILES:
        req = urllib.request.Request(URL.format(name), headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            for i, raw in enumerate(r, 1):
                # cheap pre-filter before JSON parsing: the ASIN must appear in the line
                line = raw.decode("utf-8", "replace")
                k = line.find('"parent_asin": "')
                asin = line[k + 16:k + 26] if k >= 0 else None
                if asin in wanted:
                    item = json.loads(line)
                    found[asin] = {"price": parse_price(item.get("price")), "title": item.get("title"),
                                   "store": item.get("store"), "main_category": item.get("main_category"),
                                   "rating": item.get("average_rating"), "ratings": item.get("rating_number")}
                if i % 500_000 == 0:
                    print(f"  {name}: {i:,} lines, {len(found)} matches", flush=True)
    OUT.write_text(json.dumps(found), encoding="utf-8")
    priced = sum(1 for v in found.values() if v["price"])
    print(f"matched {len(found)} of {len(wanted)} ABO products; {priced} have a price -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
