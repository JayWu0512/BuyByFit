"""IKEA CommerceTXT parsing: inches with fractions (incl. IKEA's missing spaces), real price and link."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.product.ikea_import import parse_file, parse_size  # noqa: E402

SAMPLE = """# @PRODUCT
Name: HAVSTA Coffee table, white
SKU: 00404204
Brand: IKEA
URL: https://www.ikea.com/us/en/p/havsta-coffee-table-white-00404204/
Category: Coffee tables
Description: , 39 3/8x29 1/2". Made of solid wood with crafted details.

# @OFFER
Price: 249.99
Currency: USD
Availability: InStock

# @SPECS
Materials: Leg: Solid pine, Table top: Solid pine

# @IMAGES
Main: https://www.ikea.com/us/en/images/products/havsta-coffee-table-white__1294504_pe935479_s5.jpg
"""


def test_parse_size_fractions_and_missing_spaces():
    assert parse_size(', 46 1/2x30 3/4". Separate shelf') == (118.1, 78.1)
    assert parse_size(', 451/4x227/8" A stylish statement') == (114.9, 58.1)     # 45 1/4 x 22 7/8
    assert parse_size(', 16" KRANSBORRE cushion') == (40.6, None)
    assert parse_size("no size here") == (None, None)


def test_parse_dims_every_ikea_format():
    from app.services.product.ikea_import import parse_dims
    assert parse_dims("BILLY bookcase, white", ', 311/2x11x791/2" BILLY bookcase', "SHELF") == (80.0, 27.9, 201.9, "listing")
    assert parse_dims("HAVSTA Coffee table", ", 39 3/8x29 1/2\". Made of", "TABLE")[:3] == (100.0, 74.9, None)
    assert parse_dims("LOHALS rug, flatwoven", ', 6\'7"x9\'10" Crafted with jute', "RUG")[:3] == (200.7, 299.7, 1.0)
    assert parse_dims("STOENSE Rug", ", 5 ' 7\"x7 ' 10\". The thick", "RUG")[:2] == (170.2, 238.8)
    assert parse_dims("NORDKISA Nightstand, bamboo, Width: 23 5/", '8". A handy companion', "TABLE")[:1] == (60.0,)
    assert parse_dims("VEDBO Armchair, Gunnared dark gray, Height including back cushions: 29 1/", '2". The timeless',
                      "CHAIR")[:3] == (None, None, 74.9)
    assert parse_dims("BERÄKNA Vase, clear glass, Height: 17 ¾\"", "BERÄKNA Vase", "VASE")[:3] == (None, None, 45.1)
    assert parse_dims("STOCKHOLM 2025 floor lamp", ', 63" This lamp has', "LAMP")[:3] == (None, None, 160.0)
    assert parse_dims("KLEPPSTAD bed frame, white, Queen", "KLEPPSTAD has a stylish", "BED") == (162.6, 213.4, None, "mattress size")
    assert parse_dims("FLINSHULT armchair, beige", "With its durable upholstery", "CHAIR") == (None, None, None, "none")


def test_parse_file_real_price_link_and_type():
    p = parse_file(SAMPLE, "coffee-tables")
    assert p["id"] == "ikea:00404204" and p["product_type"] == "TABLE"
    assert p["price"] == 249.99 and p["currency"] == "USD"
    assert p["url"].startswith("https://www.ikea.com/us/en/p/")
    assert (p["width_cm"], p["depth_cm"], p["height_cm"]) == (100.0, 74.9, None)
    assert p["description"].startswith("Made of solid wood") and p["color"] == "white"
