"""Human labelling page: the eval set, and the referee for which teacher to trust.

    uv run python label_ui.py sample --n 100      # pick the set once the scrape is done (fixed seed)
    uv run python label_ui.py serve               # http://127.0.0.1:8765  (local only)

The sample mixes before/after pairs ("which room is better designed?") and single photos (score 1-10 + weak
spots). Teacher labels are never shown, so your judgement stays independent. Pairs use the same random A/B order
as label.py. Labels go to data/labels_human.jsonl (append-only; the latest entry per item wins).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from label import PRINCIPLES, a_is_before

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SAMPLE = DATA / "human_sample.jsonl"
LABELS = DATA / "labels_human.jsonl"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


# ---------------------------------------------------------------- sampling

def sample(n: int, pair_share: float, seed: int):
    images = jsonl(DATA / "images.jsonl")
    pairs = jsonl(DATA / "pairs.jsonl")
    teacher = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
    # Page-candidate pairs are often two different rooms: only use them once the teacher has confirmed same_room
    # (it only answers "same room?" here; which room is better stays your call). Labelled/composite pairs are kept.
    pair_check = {r["pair_id"]: r["label"] for r in jsonl(DATA / "labels_pairs.jsonl")}
    pairs = [p for p in pairs if p["source"] != "page_candidate"
             or (pair_check.get(p["pair_id"], {}).get("same_room") and pair_check[p["pair_id"]].get("both_interiors"))]
    # Singles: skip images the teacher already flagged as composites (they show up as pairs) or non-interiors.
    used_in_pairs = {p["before"] for p in pairs} | {p["after"] for p in pairs}
    singles = [i for i in images if i["id"] not in used_in_pairs
               and teacher.get(i["id"], {}).get("composite", "none") == "none"
               and teacher.get(i["id"], {}).get("kind", "interior_photo") == "interior_photo"]
    rng = random.Random(seed)
    n_pairs = min(len(pairs), round(n * pair_share))
    # Spread over sites so one big site can't dominate the eval.
    def spread(pool, k):
        by_site = {}
        for x in rng.sample(pool, len(pool)):
            by_site.setdefault(x["domain"], []).append(x)
        out, sites = [], list(by_site)
        while len(out) < k and any(by_site.values()):
            for s in sites:
                if by_site[s] and len(out) < k:
                    out.append(by_site[s].pop())
        return out
    chosen = [{"item_id": p["pair_id"], "type": "pair", "domain": p["domain"], "page_url": p["page_url"],
               "a_is_before": a_is_before(p["pair_id"]),
               "a": p["before_file"] if a_is_before(p["pair_id"]) else p["after_file"],
               "b": p["after_file"] if a_is_before(p["pair_id"]) else p["before_file"]}
              for p in spread(pairs, n_pairs)]
    chosen += [{"item_id": s["id"], "type": "single", "domain": s["domain"], "page_url": s["page_url"], "a": s["file"]}
               for s in spread(singles, n - len(chosen))]
    rng.shuffle(chosen)
    with SAMPLE.open("w", encoding="utf-8") as f:
        for c in chosen:
            f.write(json.dumps(c) + "\n")
    print(f"{len(chosen)} items ({n_pairs} pairs, {len(chosen) - n_pairs} singles) from "
          f"{len({c['domain'] for c in chosen})} sites -> {SAMPLE}")


# ---------------------------------------------------------------- server

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Taste Labelling</title>
<style>
:root{--bg:#f7f5f0;--panel:#fff;--fg:#292b28;--muted:#6b6b66;--line:#d9d4ca;--accent:#65513f;--on:#292b28;--onfg:#fff;--good:#3d6b45;--warn:#9a4b2f}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--panel:#1f1f1d;--fg:#ecebe6;--muted:#9a9993;--line:#34342f;--accent:#c9a988;--on:#ecebe6;--onfg:#161615;--good:#7fb38a;--warn:#e0937a}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:10px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header h1{font-size:16px;margin:0} .bar{flex:1;min-width:160px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)} .muted{color:var(--muted)} main{padding:12px 16px 120px;max-width:1500px;margin:auto}
.imgs{display:grid;gap:12px} .imgs.two{grid-template-columns:1fr 1fr} @media(max-width:760px){.imgs.two{grid-template-columns:1fr}}
figure{margin:0;position:relative} figure img{width:100%;max-height:68vh;object-fit:contain;background:#0002;border-radius:8px;display:block}
figure b{position:absolute;top:8px;left:8px;background:var(--on);color:var(--onfg);padding:2px 10px;border-radius:999px;font-size:14px}
figure.pick img{outline:4px solid var(--accent);outline-offset:2px}
.panel{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
.group{display:flex;gap:6px;flex-wrap:wrap;align-items:center} .group>span{color:var(--muted);font-size:13px;margin-right:2px}
button{font:inherit;font-size:14px;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:6px 10px;cursor:pointer}
button.on{background:var(--on);color:var(--onfg);border-color:var(--on)} button.save{background:var(--accent);color:var(--onfg);border-color:var(--accent);font-weight:600}
kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px;color:var(--muted);margin-left:4px}
input[type=text]{font:inherit;font-size:16px;flex:1;min-width:200px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.done{color:var(--good);font-weight:600} .src{font-size:12px} .src a{color:inherit}
</style></head><body>
<header><h1>Taste labelling</h1><div class="bar"><i id="prog"></i></div><span id="count" class="muted"></span>
<span class="muted" style="font-size:13px"><kbd>←</kbd><kbd>→</kbd> move · <kbd>Enter</kbd> save &amp; next · <kbd>x</kbd> skip (not a usable interior) · <kbd>n</kbd> note</span></header>
<main><p id="meta" class="muted src"></p><div id="imgs" class="imgs"></div></main>
<div class="panel" id="panel"></div>
<script>
const P = __PRINCIPLES__, KEYS = "qwertyu";
let items = [], labels = {}, i = 0, cur = {};
const $ = s => document.querySelector(s);
async function load(){ const r = await fetch("/api/items"); const j = await r.json(); items = j.items; labels = j.labels;
  i = Math.max(0, items.findIndex(x => !labels[x.item_id])); if (i < 0) i = 0; show(); }
function show(){
  const it = items[i]; if (!it) return;
  cur = JSON.parse(JSON.stringify(labels[it.item_id] || (it.type === "pair" ? {better:null, margin:null, same_room:true, note:""} : {overall:null, weak:[], note:""})));
  const done = Object.keys(labels).length;
  $("#prog").style.width = (100*done/items.length)+"%";
  $("#count").textContent = `${i+1} / ${items.length} · ${done} labelled`;
  $("#meta").innerHTML = `${it.type === "pair" ? "Pair: which room is better DESIGNED? (ignore photo quality)" : "Single: how good is this room's design?"} · <a href="${it.page_url}" target="_blank" rel="noreferrer">${it.domain}</a>` + (labels[it.item_id] ? ' · <span class="done">saved</span>' : "");
  const imgs = $("#imgs"); imgs.className = "imgs" + (it.type === "pair" ? " two" : "");
  imgs.innerHTML = it.type === "pair"
    ? `<figure id="fa"><b>A</b><img src="/data/${it.a}"></figure><figure id="fb"><b>B</b><img src="/data/${it.b}"></figure>`
    : `<figure><img src="/data/${it.a}"></figure>`;
  render();
}
function render(){
  const it = items[i], p = $("#panel");
  const btn = (txt, on, act, k) => `<button class="${on?"on":""}" onclick="${act}">${txt}${k?`<kbd>${k}</kbd>`:""}</button>`;
  let h = "";
  if (it.type === "pair"){
    h += `<div class="group"><span>Better</span>${btn("A", cur.better==="A","setv('better','A')","a")}${btn("B", cur.better==="B","setv('better','B')","b")}${btn("Tie", cur.better==="tie","setv('better','tie')","t")}</div>`;
    h += `<div class="group"><span>By how much</span>${[1,2,3,4,5].map(m => btn(m, cur.margin===m, `setv('margin',${m})`, "")).join("")}<span class="muted">(keys 1-5)</span></div>`;
    h += `<div class="group">${btn("Different rooms", !cur.same_room, "setv('same_room',!cur.same_room)", "d")}</div>`;
    document.getElementById("fa")?.classList.toggle("pick", cur.better==="A");
    document.getElementById("fb")?.classList.toggle("pick", cur.better==="B");
  } else {
    h += `<div class="group"><span>Design</span>${[1,2,3,4,5,6,7,8,9,10].map(s => btn(s, cur.overall===s, `setv('overall',${s})`, "")).join("")}<span class="muted">(keys 1-9, 0 = 10)</span></div>`;
    h += `<div class="group"><span>Weak spots</span>${Object.keys(P).map((k,j) => btn(k.replace("_"," "), cur.weak.includes(k), `toggleWeak('${k}')`, KEYS[j])).join("")}</div>`;
  }
  h += `<input type="text" id="note" placeholder="Note (optional): what makes it good or bad?" value="${(cur.note||"").replace(/"/g,"&quot;")}" oninput="cur.note=this.value">`;
  h += `<button class="save" onclick="save()">Save &amp; next<kbd>Enter</kbd></button>`;
  p.innerHTML = h;
}
function setv(k, v){ cur[k] = v; render(); }
function toggleWeak(k){ cur.weak = cur.weak.includes(k) ? cur.weak.filter(x => x!==k) : [...cur.weak, k]; render(); }
async function post(body){
  const r = await fetch("/api/label", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  if (!r.ok) { alert("Save failed: " + await r.text()); return false; } return true;
}
async function save(skip=false){
  const it = items[i];
  if (!skip){
    if (it.type === "pair" && cur.same_room && !cur.better) return flash("Pick A, B or Tie (or mark Different rooms)");
    if (it.type === "single" && !cur.overall) return flash("Pick a score 1-10 (or x to skip)");
  }
  const body = {item_id: it.item_id, type: it.type, skip, ...cur};
  if (it.type === "pair"){ body.a_is_before = it.a_is_before;
    body.after_wins = (!cur.better || cur.better === "tie") ? null : ((cur.better === "B") === it.a_is_before); }
  if (await post(body)){ labels[it.item_id] = cur; if (i < items.length - 1) i++; show(); }
}
function flash(msg){ const m = $("#meta"); m.innerHTML = `<span style="color:var(--warn)">${msg}</span>`; setTimeout(show, 1400); }
document.addEventListener("keydown", e => {
  if (e.target.id === "note"){ if (e.key === "Enter") { e.preventDefault(); save(); } if (e.key === "Escape") e.target.blur(); return; }
  const it = items[i]; if (!it) return; const k = e.key;
  if (k === "ArrowRight"){ if (i < items.length-1){ i++; show(); } return; }
  if (k === "ArrowLeft"){ if (i > 0){ i--; show(); } return; }
  if (k === "Enter"){ e.preventDefault(); save(); return; }
  if (k === "x"){ save(true); return; }
  if (k === "n"){ e.preventDefault(); $("#note").focus(); return; }
  if (it.type === "pair"){
    if (k === "a") setv("better","A"); else if (k === "b") setv("better","B"); else if (k === "t") setv("better","tie");
    else if (k === "d") setv("same_room", !cur.same_room); else if ("12345".includes(k)) setv("margin", +k);
  } else {
    if ("123456789".includes(k)) setv("overall", +k); else if (k === "0") setv("overall", 10);
    else if (KEYS.includes(k)) toggleWeak(Object.keys(P)[KEYS.indexOf(k)]);
  }
});
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            page = PAGE.replace("__PRINCIPLES__", json.dumps(PRINCIPLES))
            return self.send(200, page.encode(), "text/html; charset=utf-8")
        if self.path == "/api/items":
            latest = {}
            for r in jsonl(LABELS):
                latest[r["item_id"]] = {k: v for k, v in r.items() if k not in ("item_id", "type", "at")}
            return self.send(200, json.dumps({"items": jsonl(SAMPLE), "labels": latest}).encode())
        if self.path.startswith("/data/"):
            path = (DATA / self.path[len("/data/"):]).resolve()
            if DATA.resolve() not in path.parents or path.suffix.lower() not in (".jpg", ".jpeg", ".png") or not path.is_file():
                return self.send(404, b"not found", "text/plain")
            return self.send(200, path.read_bytes(), "image/jpeg")
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/label":
            return self.send(404, b"not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
            known = {x["item_id"] for x in jsonl(SAMPLE)}
            if body.get("item_id") not in known:
                return self.send(400, b"unknown item", "text/plain")
        except (ValueError, KeyError):
            return self.send(400, b"bad json", "text/plain")
        body["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with LABELS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
        self.send(200, b'{"ok":true}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=100)
    s.add_argument("--pair-share", type=float, default=0.4, help="fraction of the sample that is pairs")
    s.add_argument("--seed", type=int, default=7)
    v = sub.add_parser("serve")
    v.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if args.cmd == "sample":
        if SAMPLE.exists() and jsonl(LABELS):
            sys.exit(f"{SAMPLE.name} already has labels against it; delete {LABELS.name} first if you really want a new sample")
        sample(args.n, args.pair_share, args.seed)
    else:
        if not SAMPLE.exists():
            sys.exit("Run `label_ui.py sample` first")
        print(f"Labelling page: http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
