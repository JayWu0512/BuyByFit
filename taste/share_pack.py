"""A one-file labelling pack for an outside expert (no server, no login): pick rooms, embed them, send the HTML.

    uv run python share_pack.py make --n 10 --name architect     # -> data/share/architect_pack.html
    uv run python share_pack.py import results.json              # her downloaded results -> data/labels_expert.jsonl

Picks professionally designed rooms (teacher state "designed"/"staged") from the human eval sample, so her scores
line up with yours and the models' on the same photos. Spread over sites and over the teacher's score range.
The file embeds the images, so it is private material: send it directly, don't post it.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from label import PRINCIPLES

DATA = Path(__file__).resolve().parent / "data"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def pick(n: int, seed: int) -> list[dict]:
    teacher = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
    pool = [s for s in jsonl(DATA / "human_sample.jsonl") if s["type"] == "single"
            and teacher.get(s["item_id"], {}).get("state") in ("designed", "staged")
            and teacher[s["item_id"]].get("kind") == "interior_photo"]
    rng = random.Random(seed)
    rng.shuffle(pool)
    # Round-robin over sites, then over teacher scores, so it isn't ten 8/10 rooms from one studio.
    pool.sort(key=lambda s: teacher[s["item_id"]]["overall"])
    by_site: dict[str, list] = {}
    for s in pool:
        by_site.setdefault(s["domain"], []).append(s)
    chosen = []
    while len(chosen) < n and any(by_site.values()):
        for site in list(by_site):
            if by_site[site] and len(chosen) < n:
                chosen.append(by_site[site].pop(rng.randrange(len(by_site[site]))))
    rng.shuffle(chosen)
    return chosen


def embed(path: Path) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((1400, 1400))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Room Design Review</title>
<style>
:root{--bg:#f7f5f0;--panel:#fff;--fg:#292b28;--muted:#686a63;--line:#d9d4ca;--accent:#65513f;--on:#292b28;--onfg:#fff;--ok:#3d6b45}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--panel:#1f1f1d;--fg:#ecebe6;--muted:#9a9993;--line:#34342f;--accent:#c9a988;--on:#ecebe6;--onfg:#161615;--ok:#7fb38a}}
:root[data-theme=dark]{--bg:#161615;--panel:#1f1f1d;--fg:#ecebe6;--muted:#9a9993;--line:#34342f;--accent:#c9a988;--on:#ecebe6;--onfg:#161615;--ok:#7fb38a}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 Georgia,"Times New Roman",serif}
.wrap{max-width:900px;margin:0 auto;padding:24px 16px 80px}
h1{font-weight:500;font-size:28px;margin:0 0 6px} .lead{color:var(--muted);font:15px/1.55 system-ui,sans-serif;margin:0 0 18px}
.sans{font-family:system-ui,sans-serif}
.intro{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;font:14px/1.55 system-ui,sans-serif}
.intro ul{margin:6px 0 0;padding-left:18px} .intro b{font-weight:600}
label.name{display:block;margin:16px 0 0;font:14px system-ui,sans-serif;color:var(--muted)}
input,textarea{font:16px system-ui,sans-serif;width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
.room{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:22px 0;overflow:hidden}
.room img{width:100%;display:block;background:#0002}
.body{padding:14px 16px 16px;font-family:system-ui,sans-serif}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}
.row>span{color:var(--muted);font-size:13px;width:100%}
button{font:15px system-ui,sans-serif;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:8px 0;min-width:40px;cursor:pointer}
button.chip{padding:6px 11px;min-width:0;border-radius:999px;font-size:14px}
button.on{background:var(--on);color:var(--onfg);border-color:var(--on)}
.num{color:var(--muted);font-size:13px} .done{color:var(--ok);font-weight:600}
.send{position:sticky;bottom:0;background:var(--panel);border-top:1px solid var(--line);padding:12px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-family:system-ui,sans-serif}
.send button{padding:10px 16px;min-width:0} .send .primary{background:var(--accent);color:var(--onfg);border-color:var(--accent);font-weight:600}
#status{color:var(--muted);font-size:14px;flex:1;min-width:160px}
</style></head><body>
<div class="wrap">
<h1>Room design review</h1>
<p class="lead">__N__ interiors. About 10 minutes. Your scores help train a model that judges interior design.</p>
<div class="intro"><b>For each room:</b>
<ul><li><b>Score the design 1-10</b>: the space itself (layout, proportion, light, materials, cohesion), not the quality of the photo.</li>
<li><b>Tick its weak spots</b>, if any.</li><li><b>A short note</b> helps most: what works, what you would change.</li></ul>
<p style="margin:8px 0 0">1-3 poor · 4-5 mediocre · 6-7 good · 8-9 very good · 10 exceptional</p></div>
<label class="name">Your name<input id="who" placeholder="Name" autocomplete="name"></label>
<div id="rooms"></div>
</div>
<div class="wrap" id="outwrap" hidden style="padding-top:0"><div class="intro">
<b>Your results.</b> If the buttons didn't work: tap in the box, select all, copy, and paste it into a message
(or just take a screenshot).<textarea id="out" rows="8" readonly style="margin-top:8px;font:12px ui-monospace,monospace"></textarea></div></div>
<div class="send"><span id="status"></span>
<button onclick="showResults()">Show results</button><button onclick="emailResults()">Email results</button>
<button onclick="copyResults()">Copy results</button><button class="primary" onclick="download()">Download results</button></div>
<script>
const ROOMS = __ROOMS__, P = __PRINCIPLES__, PACK = "__PACK__";
const KEY = "taste-pack-" + PACK;
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} status(); }
function status(){ const n = ROOMS.filter(r => (state[r.id]||{}).overall).length;
  document.getElementById("status").innerHTML = n === ROOMS.length ? `<span class="done">All ${n} scored.</span> Download or copy, and send it back.` : `${n} of ${ROOMS.length} scored`; }
function get(id){ return state[id] || (state[id] = {overall: null, weak: [], note: ""}); }
function render(){
  document.getElementById("rooms").innerHTML = ROOMS.map((r, i) => { const s = get(r.id);
    return `<section class="room" id="r${i}"><img src="${r.src}" alt="Room ${i+1}" loading="lazy"><div class="body">
      <div class="num">Room ${i+1} of ${ROOMS.length}</div>
      <div class="row"><span>Design score</span>${[1,2,3,4,5,6,7,8,9,10].map(v => `<button class="${s.overall===v?"on":""}" onclick="setScore('${r.id}',${v})">${v}</button>`).join("")}</div>
      <div class="row"><span>Weak spots (optional)</span>${Object.entries(P).map(([k, d]) => `<button class="chip ${s.weak.includes(k)?"on":""}" title="${d.replace(/"/g,'&quot;')}" onclick="toggle('${r.id}','${k}')">${k.replace("_"," ")}</button>`).join("")}</div>
      <textarea rows="2" placeholder="What works, what would you change?" oninput="note('${r.id}',this.value)">${(s.note||"").replace(/</g,"&lt;")}</textarea>
    </div></section>`; }).join("");
  status();
}
function setScore(id, v){ get(id).overall = v; save(); render(); }
function toggle(id, k){ const s = get(id); s.weak = s.weak.includes(k) ? s.weak.filter(x => x !== k) : [...s.weak, k]; save(); render(); }
function note(id, v){ get(id).note = v; save(); }
function results(){ return JSON.stringify({pack: PACK, rater: document.getElementById("who").value.trim(), at: new Date().toISOString(),
  labels: ROOMS.map(r => ({item_id: r.id, ...get(r.id)}))}, null, 1); }
function say(msg){ document.getElementById("status").textContent = msg; }
// The results box always works (select all + copy, or a screenshot), so every other button falls back to it.
function showResults(){ const w = document.getElementById("outwrap"), o = document.getElementById("out");
  o.value = results(); w.hidden = false; w.scrollIntoView({behavior: "smooth", block: "center"}); o.focus(); o.select(); }
function download(){
  try {
    const name = `room-review-${(document.getElementById("who").value.trim()||"results").replace(/\\W+/g,"-")}.json`;
    const url = URL.createObjectURL(new Blob([results()], {type: "application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = name; a.style.display = "none";
    document.body.appendChild(a); a.click();  // must be in the page for Firefox/Safari
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1500);
    say("Downloaded (check your Downloads folder). If nothing appeared, use Show results.");
  } catch (e) { showResults(); say("Download is blocked here: copy the text from the box below instead."); }
}
async function copyResults(){
  const text = results();
  try { await navigator.clipboard.writeText(text); say("Copied. Paste it into a message."); return; } catch (e) {}
  showResults();  // file:// pages often can't use the clipboard API: select the box and try the old way
  try { if (document.execCommand("copy")) { say("Copied. Paste it into a message."); return; } } catch (e) {}
  say("Select all in the box below and copy it, or take a screenshot.");
}
function emailResults(){
  const who = document.getElementById("who").value.trim();
  const lines = ROOMS.map((r, i) => { const s = get(r.id); return `Room ${i+1}: ${s.overall ?? "-"}/10` +
    (s.weak.length ? ` | weak: ${s.weak.join(", ")}` : "") + (s.note ? ` | ${s.note}` : ""); }).join("\\n");
  const body = `Room design review${who ? " by " + who : ""}\\n\\n${lines}\\n\\n---\\n${results()}`;
  location.href = "mailto:?subject=" + encodeURIComponent("Room design review") + "&body=" + encodeURIComponent(body);
  showResults();
}
render();
</script></body></html>"""


def make(n: int, name: str, seed: int):
    chosen = pick(n, seed)
    if len(chosen) < n:
        print(f"only {len(chosen)} designed/staged rooms available in the human sample")
    rooms = [{"id": s["item_id"], "src": embed(DATA / s["a"])} for s in chosen]
    out = DATA / "share"
    out.mkdir(exist_ok=True)
    page = (PAGE.replace("__N__", str(len(rooms))).replace("__ROOMS__", json.dumps(rooms))
            .replace("__PRINCIPLES__", json.dumps(PRINCIPLES)).replace("__PACK__", html.escape(name)))
    path = out / f"{name}_pack.html"
    path.write_text(page, encoding="utf-8")
    (out / f"{name}_pack_items.json").write_text(json.dumps([s["item_id"] for s in chosen]))
    print(f"{len(rooms)} rooms -> {path} ({path.stat().st_size / 1e6:.1f} MB)")


def replace(name: str, index: int, seed: int):
    """Swap room <index> (1-based, as numbered on the page) for another designed room; the rest keep their order.
    The removed room is remembered in <name>_pack_excluded.json so it never comes back."""
    out = DATA / "share"
    ids = json.loads((out / f"{name}_pack_items.json").read_text())
    excl_path = out / f"{name}_pack_excluded.json"
    excluded = set(json.loads(excl_path.read_text())) if excl_path.exists() else set()
    gone = ids[index - 1]
    excluded.add(gone)
    candidates = [s for s in pick(10_000, seed) if s["item_id"] not in excluded and s["item_id"] not in ids]
    if not candidates:
        raise SystemExit("no other designed/staged rooms left in the human sample")
    sample = {s["item_id"]: s for s in jsonl(DATA / "human_sample.jsonl")}
    ids[index - 1] = candidates[0]["item_id"]
    excl_path.write_text(json.dumps(sorted(excluded)))
    rebuild(name, ids)
    print(f"room {index}: {sample[gone]['domain']} ({gone}) -> {candidates[0]['domain']} ({ids[index - 1]})")


def rebuild(name: str, ids: list[str] | None = None):
    """Rewrite the page for the same rooms in the same order (e.g. after a page fix). Answers already given are
    kept by the browser (same pack name)."""
    out = DATA / "share"
    ids = ids or json.loads((out / f"{name}_pack_items.json").read_text())
    sample = {s["item_id"]: s for s in jsonl(DATA / "human_sample.jsonl")}
    rooms = [{"id": i, "src": embed(DATA / sample[i]["a"])} for i in ids]
    page = (PAGE.replace("__N__", str(len(rooms))).replace("__ROOMS__", json.dumps(rooms))
            .replace("__PRINCIPLES__", json.dumps(PRINCIPLES)).replace("__PACK__", html.escape(name)))
    (out / f"{name}_pack.html").write_text(page, encoding="utf-8")
    (out / f"{name}_pack_items.json").write_text(json.dumps(ids))


def import_results(path: Path):
    res = json.loads(path.read_text(encoding="utf-8"))
    out = DATA / "labels_expert.jsonl"
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    with out.open("a", encoding="utf-8") as f:
        for lab in res["labels"]:
            if lab.get("overall"):
                f.write(json.dumps({**lab, "rater": res.get("rater"), "pack": res.get("pack"), "imported_at": at}) + "\n")
                n += 1
    print(f"{n} expert labels from {res.get('rater') or 'unnamed'} -> {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--n", type=int, default=10)
    m.add_argument("--name", default="architect")
    m.add_argument("--seed", type=int, default=3)
    r = sub.add_parser("replace", help="swap one room (number as shown on the page)")
    r.add_argument("index", type=int)
    r.add_argument("--name", default="architect")
    r.add_argument("--seed", type=int, default=3)
    b = sub.add_parser("rebuild", help="rewrite the page for the same rooms (after a page fix)")
    b.add_argument("--name", default="architect")
    i = sub.add_parser("import")
    i.add_argument("results", type=Path)
    args = ap.parse_args()
    if args.cmd == "make":
        make(args.n, args.name, args.seed)
    elif args.cmd == "replace":
        replace(args.name, args.index, args.seed)
    elif args.cmd == "rebuild":
        rebuild(args.name)
    else:
        import_results(args.results)


if __name__ == "__main__":
    main()
