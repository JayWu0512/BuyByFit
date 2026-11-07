"""Voice -> vibe search -> AR MVP server.

    python ar-mvp/server.py              # http://localhost:8080 (and your LAN IP)

Serves the mobile page, the compressed models, and POST /api/search.
The phone needs HTTPS for the mic + AR, so put a tunnel in front (see ar-mvp/README.md).
"""
from __future__ import annotations

import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

import psycopg2.pool  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.services.product import embed  # noqa: E402
from app.services.product.index_products import database_url, search  # noqa: E402

# ---------------------------------------------------------------- voice text -> filters

_NUM = r"(\d+(?:\.\d+)?)"
# longest spellings first, so "meters" isn't read as "m" + "eters"; trailing \b stops "m" eating "made"
_UNIT = (r"(centimet(?:er|re)s?|millimet(?:er|re)s?|met(?:er|re)s?|inch(?:es)?|feet|foot"
         r"|cm\b|mm\b|m\b|in\b|ft\b|\"|')")
_TO_CM = {"cm": 1, "mm": 0.1, "m": 100, "in": 2.54, "ft": 30.48}

TYPE_WORDS = [  # first match wins; order matters ("bean bag" before "chair", "teddy bear" before "bear")
    (r"teddy( bears?)?|teddies|plush(ies|ie|y)?|stuffed (animals?|toys?|bears?|bunn(y|ies))|stuffies?|soft toys?"
     r"|cuddly toys?|toys?|dolls?", ["PLUSH_TOY"]),
    (r"piggy banks?|figurines?|sculptures?|statues?|ornaments?", ["DECOR", "FIGURINE", "SCULPTURE"]),
    (r"bean ?bags?( chairs?)?", ["BEAN_BAG_CHAIR"]),
    (r"(throw )?pillows?|cushions?", ["PILLOW"]),
    (r"planters?|plant pots?|pots?|plants?|succulents?", ["PLANTER", "ARTIFICIAL_PLANT"]),
    (r"vases?", ["VASE"]),
    (r"candle ?holders?|candlesticks?|candles?", ["CANDLE_HOLDER"]),
    (r"clocks?", ["CLOCK"]),
    (r"baskets?", ["BASKET"]),
    (r"chandeliers?|pendants?|ceiling lights?|light fixtures?", ["LIGHT_FIXTURE"]),
    (r"sofas?|couch(es)?|loveseats?|sectionals?|settees?", ["SOFA"]),
    (r"arm ?chairs?|recliners?|chairs?", ["CHAIR"]),
    (r"desks?", ["DESK"]),
    (r"(coffee |side |end |dining )?tables?|nightstands?", ["TABLE"]),
    (r"(floor |table |desk )?lamps?|lights?", ["LAMP"]),
    (r"rugs?|carpets?", ["RUG"]),
    (r"ottomans?|poufs?|footstools?", ["OTTOMAN"]),
    (r"stools?", ["STOOL_SEATING"]),
    (r"shel(f|ves)|bookcases?|bookshel(f|ves)", ["SHELF"]),
    (r"cabinets?|sideboards?|credenzas?|tv stands?|media consoles?", ["CABINET", "HOME_FURNITURE_AND_DECOR"]),
    (r"dressers?|chest of drawers", ["DRESSER", "HOME_FURNITURE_AND_DECOR"]),
    (r"beds?|bed ?frames?|headboards?", ["BED", "BED_FRAME", "HEADBOARD"]),
    (r"bench(es)?", ["BENCH"]),
]


def _unit_cm(u: str | None) -> float | None:
    if not u:
        return None
    u = u.lower()
    if u in ('"',) or u.startswith("in"):
        return _TO_CM["in"]
    if u in ("'",) or u.startswith(("ft", "fe", "fo")):
        return _TO_CM["ft"]
    if u.startswith(("mm", "milli")):
        return _TO_CM["mm"]
    if u.startswith(("cm", "centi")):
        return _TO_CM["cm"]
    if u.startswith("m"):
        return _TO_CM["m"]
    return None


def _to_cm(nums: list[float], unit: str | None) -> list[float]:
    f = _unit_cm(unit)
    if f is None:  # no unit said: small numbers are metres ("2 by 1"), otherwise cm
        f = 100 if max(nums) < 10 else 1
    return [round(n * f, 1) for n in nums]


def parse_query(text: str) -> dict:
    """'a cozy mid-century sofa that fits 230 by 100' -> vibe text + max dims + product types."""
    t = text.lower().replace("×", "x")
    out: dict = {"max_w": None, "max_d": None, "max_h": None, "types": None}
    vibe = t

    # "230 by 100 (by 90) cm"  /  "7 ft x 3 ft"  -> width x depth (x height)
    sep = r"\s*(?:by|x|\*)\s*"
    m = re.search(rf"{_NUM}\s*{_UNIT}?{sep}{_NUM}\s*{_UNIT}?(?:{sep}{_NUM}\s*{_UNIT}?)?", t)
    if m:
        nums = [float(g) for g in (m.group(1), m.group(3), m.group(5)) if g]
        unit = m.group(6) or m.group(4) or m.group(2)
        cm = _to_cm(nums, unit)
        out["max_w"], out["max_d"] = cm[0], cm[1]
        if len(cm) > 2:
            out["max_h"] = cm[2]
        vibe = vibe.replace(m.group(0), " ")

    # "under 200 cm wide", "90 inches tall", "60 cm deep"
    for key, words in (("max_w", r"wide|width|long|length"), ("max_d", r"deep|depth"), ("max_h", r"tall|high|height")):
        m = re.search(rf"{_NUM}\s*{_UNIT}?\s*(?:{words})\b", t)
        if m and out[key] is None:
            out[key] = _to_cm([float(m.group(1))], m.group(2))[0]
            vibe = vibe.replace(m.group(0), " ")

    for pattern, types in TYPE_WORDS:
        if re.search(rf"\b(?:{pattern})\b", t):
            out["types"] = types
            break

    vibe = re.sub(r"\b(that |which |to )?(fits?|fitting|under|less than|at most|max(imum)?)\b", " ", vibe)
    out["vibe"] = re.sub(r"\s+", " ", vibe).strip(" ,.") or text
    return out


def _has_type(s: str) -> bool:
    return any(re.search(rf"\b(?:{p})\b", s) for p, _ in TYPE_WORDS)


def split_items(text: str) -> list[str]:
    """'a cozy sofa, a brass lamp and a teddy bear' -> ['a cozy sofa', 'a brass lamp', 'a teddy bear'].

    Splits on commas / and / with / plus, but only where every piece names a product, so
    'a black and white rug' stays one item. Bits without a product join the next piece.
    """
    t = re.sub(r"^(i want|i need|give me|show me|put|place|add|let's add|can i (see|get|have))\s+", "", text.strip(), flags=re.I)
    parts = [p for p in re.split(r"\s*[,;]\s*|\s+(?:and|with|plus|also|then|next to|beside)\s+", t, flags=re.I) if p.strip()]
    items, carry = [], ""
    for p in parts:
        piece = f"{carry} and {p}" if carry else p
        if _has_type(piece.lower()):
            items.append(piece)
            carry = ""
        else:
            carry = piece
    if carry:
        if items:
            items[-1] = f"{items[-1]} and {carry}"
        else:
            items.append(carry)
    return items or [text]


# ---------------------------------------------------------------- app

pool: psycopg2.pool.ThreadedConnectionPool | None = None


@asynccontextmanager
async def lifespan(_app):
    global pool
    pool = psycopg2.pool.ThreadedConnectionPool(1, 4, database_url(), connect_timeout=20)
    embed.embed_query("warm up")  # load the model before the first request
    yield
    pool.closeall()


app = FastAPI(title="BuyByFit AR MVP", lifespan=lifespan)


class SearchIn(BaseModel):
    query: str
    k: int = 6


def _search_one(cur, q: dict, k: int, context: str | None = None) -> dict:
    vibe = f"{q['vibe']}. Room vibe: {context}" if context and context != q["vibe"] else q["vibe"]
    rows = search(cur, vibe, q["max_w"], q["max_d"], q["max_h"], q["types"], k, require_ar=True)
    note = None
    if not rows and q["types"]:  # nothing of that type is AR-ready + fits: widen
        rows = search(cur, vibe, q["max_w"], q["max_d"], q["max_h"], None, k, require_ar=True)
        note = "No AR-ready items of that type fit, so here are other pieces that do."
    return {"parsed": q, "note": note, "results": rows}


def _with_cursor(fn):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            out = fn(cur)
        conn.rollback()
        return out
    finally:
        pool.putconn(conn)


@app.post("/api/search")
def api_search(body: SearchIn):
    return _with_cursor(lambda cur: _search_one(cur, parse_query(body.query), body.k))


@app.post("/api/scene")
def api_scene(body: SearchIn):
    """One utterance -> several products: 'a sofa, a floor lamp and a teddy bear'."""
    pieces = split_items(body.query)[:6]
    context = parse_query(body.query)["vibe"] if len(pieces) > 1 else None
    return _with_cursor(lambda cur: {
        "items": [_search_one(cur, parse_query(p), body.k, context) for p in pieces]})


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/live")
def live():
    """Voice while in the camera: WebXR AR on Android, camera-preview fallback elsewhere."""
    return FileResponse(HERE / "static" / "live.html")


# ---------------------------------------------------------------- scan a room, decorate it for a vibe
sys.path.insert(0, str(HERE / "room"))
import room_api  # noqa: E402


def _room_search(query, types, max_w, max_d, max_h, k):
    return _with_cursor(lambda cur: search(cur, query, max_w, max_d, max_h, types, k, require_ar=True))


room_api.search_fn = _room_search
app.include_router(room_api.router)


@app.get("/room")
def room_page():
    return FileResponse(HERE / "static" / "room.html")


class GLBFiles(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.endswith(".glb"):
            resp.headers["content-type"] = "model/gltf-binary"
            resp.headers["cache-control"] = "public, max-age=86400"
        return resp


(HERE / "models").mkdir(exist_ok=True)
app.mount("/models", GLBFiles(directory=HERE / "models"), name="models")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

def lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the outbound interface
        return s.getsockname()[0]
    finally:
        s.close()


def self_signed_cert(ip: str) -> tuple[Path, Path]:
    """Cert for the LAN IP so phones get a secure context (mic + AR) after one warning."""
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    d = Path.home() / "buybyfit-data" / "certs"
    d.mkdir(parents=True, exist_ok=True)
    cert_p, key_p = d / f"{ip}.crt", d / f"{ip}.key"
    if cert_p.exists() and key_p.exists():
        return cert_p, key_p
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"BuyByFit AR {ip}")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(ip)), x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--https", action="store_true", help="self-signed HTTPS on the LAN IP (for phones)")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    if a.https:
        ip = lan_ip()
        cert, key = self_signed_cert(ip)
        port = a.port or 8443
        print(f"\n  Open on your phone (same Wi-Fi):  https://{ip}:{port}\n")
        uvicorn.run(app, host="0.0.0.0", port=port, ssl_certfile=str(cert), ssl_keyfile=str(key))
    else:
        uvicorn.run(app, host="0.0.0.0", port=a.port or 8080)
