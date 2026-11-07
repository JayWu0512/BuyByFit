"""Offline test for abo_import: builds a tiny fake ABO cache and runs the importer on it."""
import csv
import gzip
import io
import json
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "services" / "product"))
import abo_import  # noqa: E402

SOFA = {
    "item_id": "B075X4QMX3", "domain_name": "amazon.com", "3dmodel_id": "B075X4QMX3",
    "item_name": [{"language_tag": "de_DE", "value": "Sofa"}, {"language_tag": "en_US", "value": "Rivet Revolve Modern Upholstered Sofa"}],
    "brand": [{"language_tag": "en_US", "value": "Rivet"}],
    "bullet_point": [{"language_tag": "en_US", "value": "Mid-century look"}, {"language_tag": "en_US", "value": "Tapered legs"}],
    "product_type": [{"value": "SOFA"}],
    "style": [{"language_tag": "en_US", "value": "Mid-Century Modern"}],
    "color": [{"language_tag": "en_US", "standardized_values": ["Grey"], "value": "Light Grey"}],
    "item_dimensions": {
        "width": {"unit": "inches", "value": 87, "normalized_value": {"unit": "inches", "value": 87}},
        "length": {"unit": "inches", "value": 37.75, "normalized_value": {"unit": "inches", "value": 37.75}},
        "height": {"unit": "inches", "value": 33, "normalized_value": {"unit": "inches", "value": 33}},
    },
    "main_image_id": "81iZesSXYZL", "other_image_id": ["71abcDEF"],
    "node": [{"node_id": 1, "node_name": "/Categories/Furniture/Living Room Furniture/Sofas & Couches"}],
}
PHONE_CASE = {"item_id": "B000PHONE", "item_name": [{"language_tag": "en_US", "value": "Phone case"}],
              "product_type": [{"value": "CELLULAR_PHONE_CASE"}]}
NO_EN_CHAIR = {"item_id": "B000CHAIR", "item_name": [{"language_tag": "ja_JP", "value": "椅子"}],
               "product_type": [{"value": "CHAIR"}]}


def make_cache(cache: Path):
    cache.mkdir(parents=True)
    lines = "\n".join(json.dumps(x) for x in [SOFA, PHONE_CASE, NO_EN_CHAIR, SOFA]).encode()
    gz = gzip.compress(lines)
    with tarfile.open(cache / "abo-listings.tar", "w") as tar:
        info = tarfile.TarInfo("listings/metadata/listings_0.json.gz")
        info.size = len(gz)
        tar.addfile(info, io.BytesIO(gz))

    def csv_gz(path, header, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        path.write_bytes(gzip.compress(buf.getvalue().encode()))

    csv_gz(cache / "images.csv.gz", ["image_id", "height", "width", "path"],
           [["81iZesSXYZL", "256", "256", "8c/8ccb5859.jpg"], ["71abcDEF", "256", "256", "aa/aa11.jpg"]])
    csv_gz(cache / "3dmodels.csv.gz", ["3dmodel_id", "path"], [["B075X4QMX3", "3/B075X4QMX3.glb"]])


def test_import(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    make_cache(cache)
    assert abo_import.main(["--cache", str(cache), "--out", str(out)]) == 0
    products = json.loads((out / "products.json").read_text())
    assert len(products) == 1  # phone case filtered, non-English skipped, duplicate removed
    p = products[0]
    assert p["id"] == "abo:B075X4QMX3"
    assert p["title"] == "Rivet Revolve Modern Upholstered Sofa"
    assert (p["width_cm"], p["depth_cm"], p["height_cm"]) == (221.0, 95.9, 83.8)
    assert p["image_urls"][0].endswith("/images/small/8c/8ccb5859.jpg")
    assert p["model_3d_url"].endswith("/3dmodels/original/3/B075X4QMX3.glb")
    assert p["category"] == ["Categories", "Furniture", "Living Room Furniture", "Sofas & Couches"]
    assert p["style"] == "Mid-Century Modern" and p["color"] == "Grey"
    rows = list(csv.DictReader(open(out / "products.csv")))
    assert rows[0]["width_cm"] == "221.0"


def test_dim_cm_rejects_zero_and_unit_errors():
    def d(v, unit="centimeters"):
        return {"unit": unit, "value": v}
    assert abo_import.dim_cm(d(81)) == 81.0
    assert abo_import.dim_cm(d(87, "inches")) == 221.0
    assert abo_import.dim_cm(d(0)) is None       # ABO uses 0 for "not filled in"
    assert abo_import.dim_cm(d(845)) is None     # Solimo sofas: >6 m is a unit error
    assert abo_import.dim_cm(d(5, "parsecs")) is None


def test_filters(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    make_cache(cache)
    abo_import.main(["--cache", str(cache), "--out", str(out), "--types", "CHAIR"])
    assert json.loads((out / "products.json").read_text()) == []
