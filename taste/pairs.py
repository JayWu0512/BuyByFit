"""Build before/after pairs from the scraped images, and a local review gallery.

    uv run python pairs.py      # -> data/pairs.jsonl, data/split/*.jpg, data/gallery.html

Three ways a pair shows up on these sites:
  1. labelled  a "before" image followed by an "after" image on the same page (alt text, filename, slider)
  2. page      a page with "before" images whose other photos are the reveal ("REVEAL", "makeover", no "after"):
               each before x each other interior photo on the page becomes a CANDIDATE pair; the teacher's
               same_room check (label.py pairs) keeps the real ones
  3. composite one image holding both photos side by side / stacked (from label.py singles): split in two
Teacher labels (data/labels_singles.jsonl), when present, drop non-interiors and renders and find composites.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
MAX_CANDIDATES_PER_BEFORE = 4


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def split_composite(rec: dict, label: dict) -> tuple[str, str] | None:
    """Crop a composite into before/after halves. Returns their files (relative to data/)."""
    side, mode = label.get("before_side"), label.get("composite")
    if mode not in ("left_right", "top_bottom") or side not in ("left", "right", "top", "bottom"):
        return None
    im = Image.open(DATA / rec["file"])
    w, h = im.size
    halves = ([im.crop((0, 0, w // 2, h)), im.crop((w - w // 2, 0, w, h))] if mode == "left_right"
              else [im.crop((0, 0, w, h // 2)), im.crop((0, h - h // 2, w, h))])
    first_is_before = side in ("left", "top")
    before, after = halves if first_is_before else halves[::-1]
    out = DATA / "split"
    out.mkdir(exist_ok=True)
    before.save(out / f"{rec['id']}_before.jpg", quality=90)
    after.save(out / f"{rec['id']}_after.jpg", quality=90)
    return f"split/{rec['id']}_before.jpg", f"split/{rec['id']}_after.jpg"


def make_pairs(images: list[dict], labels: dict[str, dict]):
    def usable(rec):  # unknown (not labelled yet) counts as usable
        lab = labels.get(rec["id"])
        return lab is None or (lab.get("kind") == "interior_photo" and lab.get("composite", "none") == "none")

    pairs, used = [], set()
    # 3. composites
    for rec in images:
        lab = labels.get(rec["id"])
        if lab and lab.get("composite") in ("left_right", "top_bottom"):
            files = split_composite(rec, lab)
            if files:
                used.add(rec["id"])
                pairs.append({"pair_id": f"{rec['id']}_split", "source": "composite", "page_url": rec["page_url"],
                              "domain": rec["domain"], "before": rec["id"], "after": rec["id"],
                              "before_file": files[0], "after_file": files[1]})
    by_page = defaultdict(list)
    for rec in images:
        if rec["id"] not in used and usable(rec):
            by_page[rec["page_url"]].append(rec)
    for page, recs in by_page.items():
        recs.sort(key=lambda r: r["order"])
        befores = [r for r in recs if r["ba_guess"] == "before"]
        if not befores:
            continue
        # 1. labelled: before -> the next "after"
        for b in befores:
            nxt = next((r for r in recs if r["order"] > b["order"] and r["ba_guess"] == "after" and r["id"] not in used), None)
            if nxt:
                used |= {b["id"], nxt["id"]}
                pairs.append(pair(b, nxt, "labelled"))
        # 2. page: remaining befores x the page's other photos (nearest first); the teacher checks same_room
        others = [r for r in recs if r["ba_guess"] != "before" and r["id"] not in used]
        for b in (b for b in befores if b["id"] not in used):
            for o in sorted(others, key=lambda r: abs(r["order"] - b["order"]))[:MAX_CANDIDATES_PER_BEFORE]:
                pairs.append(pair(b, o, "page_candidate"))
    singles = [r for r in images if r["id"] not in used and not any(p["before"] == r["id"] for p in pairs)]
    return pairs, singles


def pair(b: dict, a: dict, source: str) -> dict:
    return {"pair_id": f"{b['id']}_{a['id']}", "source": source, "page_url": b["page_url"], "domain": b["domain"],
            "before": b["id"], "after": a["id"], "before_file": b["file"], "after_file": a["file"]}


def gallery(pairs, singles, images, labels, pair_labels):
    by_id = {i["id"]: i for i in images}

    def fig(file, tag="", cap=""):
        return (f'<figure><a href="{file}" target="_blank"><img loading="lazy" src="{file}"></a>'
                f'<figcaption><b>{html.escape(tag)}</b> {html.escape(cap[:110])}</figcaption></figure>')

    rows = [f"<h2>Pairs ({len(pairs)})</h2>"]
    for p in pairs:
        pl = pair_labels.get(p["pair_id"])
        note = ""
        if pl:
            note = (f"same room: {pl.get('same_room')} · better: {pl.get('better')} (margin {pl.get('margin')}) · "
                    f"{pl.get('why', '')}")
        rows.append(f'<section class="pair"><div class="row">{fig(p["before_file"], "before")}{fig(p["after_file"], "after")}</div>'
                    f'<p>{html.escape(p["source"])} · <a href="{html.escape(p["page_url"])}" target="_blank">'
                    f'{html.escape(p["domain"])}</a> {html.escape(note)}</p></section>')
    rows.append(f"<h2>Singles ({len(singles)})</h2><div class='grid'>")
    for s in singles:
        lab = labels.get(s["id"]) or {}
        tag = f"{lab.get('overall', '')}/10 {lab.get('kind', '')}" if lab else (s["ba_guess"] or "")
        rows.append(fig(s["file"], tag, lab.get("verdict") or s.get("alt") or ""))
    rows.append("</div>")
    (DATA / "gallery.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>Taste data</title>
<style>
:root{{color-scheme:light dark;--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--muted:#9a9993;--line:#2c2c2a}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0 16px 40px}}
h2{{margin-top:28px;border-top:1px solid var(--line);padding-top:14px}}
.pair{{margin:14px 0}} .row{{display:flex;gap:10px;flex-wrap:wrap}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}}
figure{{margin:0}} .row img{{height:260px;max-width:100%;object-fit:cover;border-radius:6px;display:block}}
.grid img{{width:100%;height:170px;object-fit:cover;border-radius:6px;display:block}}
figcaption{{color:var(--muted);font-size:12px;margin-top:3px}} p{{margin:4px 0;font-size:12px;color:var(--muted)}}
a{{color:inherit}}
</style><h1>Scraped interiors: {len(images)} images</h1>{''.join(rows)}""", encoding="utf-8")


def main():
    images = jsonl(DATA / "images.jsonl")
    labels = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
    pair_labels = {r["pair_id"]: r["label"] for r in jsonl(DATA / "labels_pairs.jsonl")}
    pairs, singles = make_pairs(images, labels)
    with (DATA / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    gallery(pairs, singles, images, labels, pair_labels)
    count = defaultdict(int)
    for p in pairs:
        count[p["source"]] += 1
    print(f"{len(images)} images ({len(labels)} labelled) -> {len(pairs)} pairs {dict(count)}, "
          f"{len(singles)} singles -> data/gallery.html")


if __name__ == "__main__":
    main()
