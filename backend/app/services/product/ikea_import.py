"""IKEA US products (CommerceTXT snapshot, July 2025) -> our normalized product records.

Source: huggingface.co/datasets/tsazan/ikea-us-commercetxt (CC0 dataset; the dataset says it's for
non-commercial, educational and research use; IKEA product data and photos belong to IKEA).
Each product has a real ikea.com link, a real USD price, availability, materials and a photo.
Dimensions are written several ways (W x D x H, W x D, feet for rugs, labelled "Width: ..."); see parse_dims.
Used by price_model_ikea.py as a source of real prices.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = "tsazan/ikea-us-commercetxt"
IN_TO_CM = 2.54

# IKEA category folder -> our product_type
CATEGORY_TYPES = {  # folder names as they exist in the dataset (checked)
    "three-seat-sofas": "SOFA", "sofas-with-chaise": "SOFA", "loveseats": "SOFA",
    "fabric-armchairs": "CHAIR", "leather-armchairs": "CHAIR", "rattan-armchairs": "CHAIR",
    "dining-chairs": "CHAIR", "office-chairs": "CHAIR", "desk-chairs-for-home": "CHAIR", "folding-chairs": "CHAIR",
    "coffee-tables": "TABLE", "end-tables-and-side-tables": "TABLE", "nightstands": "TABLE",
    "extendable-tables": "TABLE", "console-sofa-and-entryway-tables": "TABLE", "desks-for-home": "DESK",
    "bed-frames": "BED", "upholstered-beds": "BED", "bookshelves-and-bookcases": "SHELF",
    "dressers-and-chests-of-drawers": "DRESSER", "buffet-tables-sideboards-and-buffet-cabinets": "CABINET",
    "fabric-ottomans": "OTTOMAN", "dining-benches": "BENCH", "hallway-benches": "BENCH",
    "bar-stools-and-chairs": "STOOL_SEATING", "floor-lamps": "LAMP", "table-lamps": "LAMP", "desk-lamps": "LAMP",
    "decorative-pendant-lamps": "LIGHT_FIXTURE", "medium-large-and-extra-large-rugs": "RUG", "handmade-rugs": "RUG",
    "indoor-plant-pots": "PLANTER", "artificial-indoor-trees-and-faux-floor-plants": "ARTIFICIAL_PLANT",
    "flower-vases": "VASE", "accent-and-throw-pillows": "PILLOW", "wall-mirrors": "HOME_MIRROR",
    "decorative-mirrors": "HOME_MIRROR", "full-length-standing-mirrors": "HOME_MIRROR", "wall-clocks": "CLOCK",
    "baskets": "BASKET", "soft-toys": "PLUSH_TOY", "kids-armchairs": "CHAIR",
}

# inches with optional fraction; IKEA's text sometimes drops the space ("451/4" = 45 1/4)
_IN = r"(\d+)(?:\s?(\d)/(\d{1,2}))?"


def inches(whole: str, num: str | None, den: str | None) -> float:
    return float(whole) + (float(num) / float(den) if num and den and float(den) else 0.0)


def parse_size(text: str) -> tuple[float | None, float | None]:
    """', 46 1/2x30 3/4"' -> (118.1, 78.1) cm. Returns (width_cm, depth_cm), either may be None."""
    m = re.search(rf"{_IN}\s*[x×]\s*{_IN}\s*\"", text)
    if m:
        a, b = inches(*m.group(1, 2, 3)), inches(*m.group(4, 5, 6))
        return round(a * IN_TO_CM, 1), round(b * IN_TO_CM, 1)
    m = re.search(rf"{_IN}\s*\"", text)                       # single size, e.g. cushion 16"
    if m:
        v = round(inches(*m.group(1, 2, 3)) * IN_TO_CM, 1)
        return v, None
    return None, None


# standard US mattress sizes (inches, width x length), for bed frames that only say "Queen"
BED_SIZES = {"california king": (72, 84), "king": (76, 80), "queen": (60, 80), "full/double": (54, 75),
             "full": (54, 75), "twin xl": (38, 80), "twin": (38, 75)}
# a single listed number means height for these types, width otherwise
SINGLE_IS_HEIGHT = {"LAMP", "PLUSH_TOY", "VASE", "ARTIFICIAL_PLANT", "HOME_MIRROR"}


def cm(x: float) -> float:
    return round(x * IN_TO_CM, 1)


def parse_dims(name: str, desc: str, ptype: str) -> tuple[float | None, float | None, float | None, str]:
    """(width, depth, height) in cm from IKEA's name + description, plus where they came from.

    Handles: W x D x H ("311/2x11x791/2\""), W x D, rugs in feet/inches (6'7"x9'10"), a single size whose
    meaning depends on the type, "Width: 23 5/" split across name and description, and bed sizes by name.
    """
    text = f"{name} {desc[:80]}"
    # rugs: feet and inches
    m = re.search(r"(\d+)\s*'\s*(\d+)?\s*\"?\s*[x×]\s*(\d+)\s*'\s*(\d+)?\s*\"", text)
    if m:
        a = int(m.group(1)) * 12 + int(m.group(2) or 0)
        b = int(m.group(3)) * 12 + int(m.group(4) or 0)
        return cm(min(a, b)), cm(max(a, b)), 1.0, "listing"
    # explicit "Width: 23 5/8"" (IKEA sometimes splits it between name and description)
    # labelled sizes, often split between name and description: "Width: 23 5/" + "8\"",
    # "Height including back cushions: 29 1/" + "2\"", "Height: 17 ¾\""
    m = re.search(r"(Width|Depth|Length|Height|Diameter)[^:,]{0,30}:\s*(\d+)(?:\s+(\d)\s*/\s*(\d+))?\s*([¼½¾])?\s*\"", text)
    if m:
        v = inches(m.group(2), m.group(3), m.group(4)) + {"¼": 0.25, "½": 0.5, "¾": 0.75}.get(m.group(5) or "", 0)
        label = m.group(1)
        if label == "Height":
            return None, None, cm(v), "listing"
        if label in ("Depth", "Length"):
            return None, cm(v), None, "listing"
        return cm(v), None, None, "listing"
    m = re.search(rf"{_IN}\s*[x×]\s*{_IN}\s*[x×]\s*{_IN}\s*\"", text)
    if m:
        w, d, h = (inches(*m.group(i, i + 1, i + 2)) for i in (1, 4, 7))
        return cm(w), cm(d), cm(h), "listing"
    m = re.search(rf"{_IN}\s*[x×]\s*{_IN}\s*\"", text)
    if m:
        a, b = inches(*m.group(1, 2, 3)), inches(*m.group(4, 5, 6))
        return cm(a), cm(b), None, "listing"
    m = re.search(rf"(?<![\d/]){_IN}\s*\"", text)
    if m:
        v = cm(inches(*m.group(1, 2, 3)))
        return (None, None, v, "listing") if ptype in SINGLE_IS_HEIGHT else (v, None, None, "listing")
    if ptype == "BED":
        low = name.lower()
        for size, (w, length) in BED_SIZES.items():
            if size in low:
                return cm(w + 4), cm(length + 4), None, "mattress size"   # frame ~2" around the mattress
    return None, None, None, "none"


def parse_file(text: str, folder: str) -> dict | None:
    def field(name):
        m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else None

    sku, url, name, image = field("SKU"), field("URL"), field("Name"), field("Main")
    if not (sku and url and name and image):
        return None
    desc = field("Description") or ""
    price = field("Price")
    ptype = CATEGORY_TYPES.get(folder, "HOME_FURNITURE_AND_DECOR")
    width, depth, height, dims_from = parse_dims(name, desc, ptype)
    materials = field("Materials")
    features = field("Features")
    return {
        "id": f"ikea:{sku}", "source": "ikea", "source_id": sku, "url": url, "title": name, "brand": "IKEA",
        "product_type": ptype,
        "category": ["IKEA", field("Category") or folder.replace("-", " ").title()],
        "style": None, "material": (materials or "")[:300] or None, "color": (name.split(",")[-1].strip() if "," in name else None),
        "price": float(price) if price else None, "currency": field("Currency") or "USD",
        "description": re.sub(r"^[,.\s]*[\d\s/x×\"']+\.?\s*", "", desc).strip() + (f" {features}" if features else ""),
        "keywords": [w for w in re.findall(r"[a-z]+", folder) if len(w) > 2],
        "image_urls": [image], "model_3d_url": None,
        "width_cm": width, "depth_cm": depth, "height_cm": height, "dims_from": dims_from,
        "caption": None, "vibe_tags": None,
        "license": "IKEA product data (CommerceTXT research snapshot, 2025-07-15); photos © IKEA",
        "scraped_at": field("LastUpdated"), "availability": field("Availability"),
    }


def load(categories: list[str]) -> list[dict]:
    """Download only the given category folders and parse them."""
    from huggingface_hub import snapshot_download
    root = Path(snapshot_download(REPO, repo_type="dataset", allow_patterns=[f"products/{c}/*.txt" for c in categories]))
    out = []
    for c in categories:
        for f in sorted((root / "products" / c).glob("*.txt")):
            p = parse_file(f.read_text(encoding="utf-8"), c)
            if p:
                out.append(p)
    return out
