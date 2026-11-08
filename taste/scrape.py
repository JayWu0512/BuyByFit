"""Polite scraper for interior before/after and project-gallery images (hackathon research set, kept private).

    uv run python scrape.py seeds.txt                # crawl every seed site
    uv run python scrape.py seeds.txt --pages 15     # fewer pages per site (quick test)

Per site: obeys robots.txt, one request every --delay seconds (default 2), stays on the seed's domain, and only
follows links that look like projects / galleries / before-after posts. Per image: keeps the largest variant
(srcset, lazy-load attributes, lightbox links), drops small ones (< --min-side px), converts to JPEG, and skips
near-duplicates (perceptual hash). Whether an image is a "before" or an "after" is guessed from its alt text,
caption, filename, nearby heading and before/after-slider markup; a vision model checks it later.

Output (data/ is gitignored, never redistributed):
    data/raw/<domain>/<id>.jpg
    data/images.jsonl   one record per image: source URLs, context text, before/after guess, size, phash
    data/state.json     visited pages and fetched image URLs, so a re-run resumes
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import threading
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

import imagehash
import requests
from bs4 import BeautifulSoup
from PIL import Image

UA = "BuyByFitTasteResearch/0.1 (student hackathon research crawler; low rate; respects robots.txt)"
DATA = Path(__file__).resolve().parent / "data"

FOLLOW = re.compile(r"before|after|project|portfolio|gallery|work|renovat|restor|remodel|makeover|reveal|"
                    r"staging|staged|transform|interior|room|bedroom|living|dining|kitchen|bath|home-tour|house",
                    re.I)
SKIP_LINK = re.compile(r"\.(pdf|zip|mp4|mov|docx?)$|/(tag|author|feed|wp-json|cart|checkout|account|login|"
                       r"privacy|terms|contact|shop|product)s?(/|$)|[?&](replytocom|share|print)=", re.I)
IMG_EXT = re.compile(r"\.(jpe?g|png|webp)(\?.*)?$", re.I)
BEFORE = re.compile(r"\bbefore\b|\bantes\b|\bvorher\b|\bavant\b|[-_]before[-_.]|[-_]bef[-_.\d]", re.I)
AFTER = re.compile(r"\bafter\b|\bdespu[eé]s\b|\bnachher\b|\bapr[eè]s\b|[-_]after[-_.]|[-_]aft[-_.\d]", re.I)
SLIDER = re.compile(r"twentytwenty|before-?after|beforeafter|ba-slider|juxtapose|cocoen|image-compare|"
                    r"img-comp|comparison-slider", re.I)
JUNK = re.compile(r"logo|icon|avatar|sprite|badge|banner-ad|favicon|placeholder|gravatar|emoji|pixel|"
                  r"button|social|pinterest|facebook|instagram", re.I)


# ---------------------------------------------------------------- polite HTTP, one session per site

class Site:
    def __init__(self, seed: str, delay: float):
        self.seed = seed
        self.host = urlsplit(seed).hostname or ""
        self.delay = delay
        self.http = requests.Session()
        self.http.headers["User-Agent"] = UA
        self._last = 0.0
        self.robots = urllib.robotparser.RobotFileParser()
        try:
            r = self.get(f"{urlsplit(seed).scheme}://{self.host}/robots.txt", check_robots=False)
            self.robots.parse(r.text.splitlines() if r is not None and r.ok else [])
        except Exception:
            self.robots.parse([])
        crawl_delay = self.robots.crawl_delay(UA)
        if crawl_delay:
            self.delay = max(self.delay, float(crawl_delay))

    def same_site(self, url: str) -> bool:
        h = urlsplit(url).hostname or ""
        return h == self.host or h.removeprefix("www.") == self.host.removeprefix("www.")

    def get(self, url: str, check_robots: bool = True, stream: bool = False):
        if check_robots and not self.robots.can_fetch(UA, url):
            return None
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            return self.http.get(url, timeout=20, stream=stream)
        except requests.RequestException:
            return None


# ---------------------------------------------------------------- page parsing

def biggest(img, base: str) -> str | None:
    """Largest variant of an <img>: srcset / data-srcset widest, else lazy-load attrs, else src."""
    best, best_w = None, -1
    for attr in ("srcset", "data-srcset", "data-lazy-srcset"):
        for part in (img.get(attr) or "").split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit() else 0
            if w > best_w:
                best, best_w = bits[0], w
    for attr in ("data-orig-file", "data-large-file", "data-full", "data-src", "data-lazy-src", "data-original", "src"):
        if best is None and img.get(attr) and not img[attr].startswith("data:"):
            best = img[attr]
    if best is None:
        return None
    # WordPress thumbnails: photo-300x200.jpg -> photo.jpg is the original
    url = urljoin(base, best)
    return re.sub(r"-\d{2,4}x\d{2,4}(?=\.(jpe?g|png|webp)(\?|$))", "", url, flags=re.I)


def context(img) -> dict:
    """Text around an image that says what it shows (and whether it's a before or an after)."""
    fig = img.find_parent("figure")
    caption = fig.figcaption.get_text(" ", strip=True) if fig and fig.figcaption else ""
    heading = ""
    h = img.find_previous(["h1", "h2", "h3", "h4"])
    if h:
        heading = h.get_text(" ", strip=True)[:160]
    classes = " ".join(" ".join(p.get("class") or []) + " " + (p.get("id") or "")
                       for p in [img, *list(img.parents)[:5]] if hasattr(p, "get"))
    # A label right before the image ("Before:" paragraph) is common on blogs.
    prev = img.find_previous(string=True)
    near = prev.strip()[:80] if prev else ""
    return {"alt": (img.get("alt") or "")[:300], "title": (img.get("title") or "")[:200], "caption": caption[:300],
            "heading": heading, "near_text": near, "classes": classes[:300]}


def ba_label(ctx: dict, url: str) -> str | None:
    text = " ".join([ctx["alt"], ctx["title"], ctx["caption"], ctx["near_text"], urlsplit(url).path.rsplit("/", 1)[-1]])
    b, a = bool(BEFORE.search(text)), bool(AFTER.search(text))
    if b != a:
        return "before" if b else "after"
    return None


def parse(html: str, url: str, site: Site):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True)[:200] if soup.title else ""
    images, seen = [], set()
    for order, img in enumerate(soup.find_all("img")):
        src = biggest(img, url)
        if not src or src in seen or not IMG_EXT.search(src) or JUNK.search(src):
            continue
        # A lightbox link around the thumbnail usually points at the full-size file.
        a = img.find_parent("a", href=True)
        if a and IMG_EXT.search(a["href"]):
            src = urljoin(url, a["href"])
        seen.add(src)
        ctx = context(img)
        images.append({"image_url": src, "order": order, **ctx, "ba_guess": ba_label(ctx, src),
                       "in_slider": bool(SLIDER.search(ctx["classes"]))})
    # Sliders often hold exactly [before, after] with no labels: label them by position.
    slider = [i for i in images if i["in_slider"]]
    if len(slider) == 2 and not any(i["ba_guess"] for i in slider):
        slider[0]["ba_guess"], slider[1]["ba_guess"] = "before", "after"
    links = []
    for a in soup.find_all("a", href=True):
        link = urldefrag(urljoin(url, a["href"]))[0]
        if not link.startswith("http") or not site.same_site(link) or SKIP_LINK.search(link) or IMG_EXT.search(link):
            continue
        if FOLLOW.search(link) or FOLLOW.search(a.get_text(" ", strip=True)[:80]):
            links.append(link)
    return title, images, links


# ---------------------------------------------------------------- run

class Store:
    def __init__(self, min_side: int):
        DATA.mkdir(exist_ok=True)
        self.min_side = min_side
        self.lock = threading.Lock()
        self.state_path = DATA / "state.json"
        st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.pages: set[str] = set(st.get("pages", []))
        self.image_urls: set[str] = set(st.get("image_urls", []))
        self.hashes: list[tuple[imagehash.ImageHash, str]] = []
        out = DATA / "images.jsonl"
        if out.exists():
            for line in out.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.hashes.append((imagehash.hex_to_hash(rec["phash"]), rec["id"]))
        self.per_site: dict[str, int] = {}
        if out.exists():
            for line in out.read_text(encoding="utf-8").splitlines():
                d = json.loads(line)["domain"]
                self.per_site[d] = self.per_site.get(d, 0) + 1
        self.out = out.open("a", encoding="utf-8")
        self.counts = {"pages": 0, "kept": 0, "small": 0, "dupe": 0, "failed": 0}
        self.max_per_site: int | None = None
        self.deadline: float | None = None  # time.time() after which crawls stop

    def site_full(self, host: str) -> bool:
        return self.max_per_site is not None and self.per_site.get(host, 0) >= self.max_per_site

    def out_of_time(self) -> bool:
        return self.deadline is not None and time.time() >= self.deadline

    def save_state(self):
        with self.lock:
            self.state_path.write_text(json.dumps({"pages": sorted(self.pages), "image_urls": sorted(self.image_urls)}))

    def add(self, site: Site, page_url: str, title: str, meta: dict):
        url = meta["image_url"]
        if self.site_full(site.host) or self.out_of_time():
            return
        with self.lock:
            if url in self.image_urls:
                return
            self.image_urls.add(url)
        r = site.get(url, stream=True)
        if r is None or not r.ok:
            self.counts["failed"] += 1
            return
        data = r.raw.read(15_000_000 + 1, decode_content=True)
        if len(data) > 15_000_000:
            return
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception:
            self.counts["failed"] += 1
            return
        if min(im.size) < self.min_side:
            self.counts["small"] += 1
            return
        im = im.convert("RGB")
        ph = imagehash.phash(im)
        with self.lock:
            dupe = next((rid for h, rid in self.hashes if h - ph <= 4), None)
            if dupe:
                self.counts["dupe"] += 1
                return
            rid = hashlib.sha1(url.encode()).hexdigest()[:16]
            self.hashes.append((ph, rid))
        folder = DATA / "raw" / site.host
        folder.mkdir(parents=True, exist_ok=True)
        im.thumbnail((2048, 2048))
        im.save(folder / f"{rid}.jpg", "JPEG", quality=90)
        rec = {"id": rid, "file": f"raw/{site.host}/{rid}.jpg", "domain": site.host, "page_url": page_url,
               "page_title": title, **meta, "width": im.width, "height": im.height, "phash": str(ph),
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with self.lock:
            self.out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.out.flush()
            self.counts["kept"] += 1
            self.per_site[site.host] = self.per_site.get(site.host, 0) + 1


def crawl(seed: str, store: Store, max_pages: int, delay: float, max_depth: int):
    site = Site(seed, delay)
    queue, queued, done = [(seed, 0)], {seed}, 0
    while queue and done < max_pages:
        if store.site_full(site.host) or store.out_of_time():
            break
        url, depth = queue.pop(0)
        # A page from an earlier run is fetched again for its links (a resumed crawl must get past it to reach
        # new pages) but doesn't count toward --pages; its images are skipped by URL in store.add.
        with store.lock:
            seen_before = url in store.pages
            store.pages.add(url)
        r = site.get(url)
        if r is None or not r.ok or "html" not in r.headers.get("content-type", ""):
            continue
        if not seen_before:
            done += 1
            store.counts["pages"] += 1
        title, images, links = parse(r.text, url, site)
        for meta in images:
            store.add(site, url, title, meta)
        if depth < max_depth:
            # Before/after pages first: they're the most valuable.
            for link in sorted(links, key=lambda u: not re.search(r"before|after|makeover|reveal|restor", u, re.I)):
                if link not in queued:
                    queued.add(link)
                    queue.append((link, depth + 1))
        store.save_state()
    print(f"  {site.host}: {done} pages", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", type=Path)
    ap.add_argument("--pages", type=int, default=60, help="max pages per site")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests to one site")
    ap.add_argument("--min-side", type=int, default=600)
    ap.add_argument("--sites-at-once", type=int, default=4)
    ap.add_argument("--max-per-site", type=int, help="stop a site once it has this many images (incl. earlier runs)")
    ap.add_argument("--stop-at", help="local time HH:MM after which every crawl stops (e.g. 22:00)")
    args = ap.parse_args()
    seeds = [s.split("#")[0].strip() for s in args.seeds.read_text().splitlines()]
    seeds = [s for s in seeds if s.startswith("http")]
    store = Store(args.min_side)
    store.max_per_site = args.max_per_site
    if args.stop_at:
        hh, mm = map(int, args.stop_at.split(":"))
        now = datetime.now()
        stop = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if stop <= now:
            raise SystemExit(f"--stop-at {args.stop_at} is already past")
        store.deadline = time.time() + (stop - now).total_seconds()
        print(f"stopping at {stop:%H:%M}", flush=True)
    print(f"{len(seeds)} sites, up to {args.pages} pages each", flush=True)
    with ThreadPoolExecutor(max_workers=args.sites_at_once) as pool:
        for f in [pool.submit(crawl, s, store, args.pages, args.delay, args.depth) for s in seeds]:
            try:
                f.result()
            except Exception as e:  # one broken site shouldn't stop the rest
                print("  site failed:", type(e).__name__, e, flush=True)
    store.save_state()
    print(json.dumps(store.counts))


if __name__ == "__main__":
    main()
