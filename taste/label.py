"""Teacher labels: filter the scraped images and critique them against the design rubric.

    uv run python label.py singles --limit 20      # critique single images (cheap test first)
    uv run python label.py pairs   --limit 20      # judge pairs: same room? which is better designed? why?
    uv run python label.py singles                  # everything not labelled yet (resumes)
    uv run python label.py singles --teacher inkling

Teachers:
  sonnet  (default) Claude Sonnet 5.5 via the Anthropic API, ANTHROPIC_API_KEY in taste/.env.
          Structured outputs guarantee the JSON shape; refusals are recorded, with server-side fallback on.
  inkling Thinking Machines Inkling via Tinker's OpenAI-compatible API, TINKER_API_KEY in taste/.env.

Pairs are shown in a random (but fixed per pair) order, so the teacher can't learn "the second one wins".
Output: data/labels_singles.jsonl, data/labels_pairs.jsonl (one teacher per file; --out to keep several).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")

SONNET = "claude-sonnet-5-5"
INKLING = "thinkingmachines/Inkling"
TINKER_OAI = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1"
MAX_SIDE = 1280  # px sent to the teacher: enough to judge design, ~1.6k image tokens

PRINCIPLES = {
    "scale": "furniture and rug sizes fit the room and each other (rug anchors the seating group)",
    "layout": "clear circulation and walkways, furniture placed for use and conversation, not just pushed to walls",
    "focal_point": "a clear focal point and visual balance",
    "lighting": "layered light (ambient, task, accent), warm and even",
    "palette": "cohesive colour story and materials, mixed textures that relate",
    "restraint": "edited decor, breathing room, no clutter",
    "cohesion": "a consistent style executed well (judge how well it does ITS style, not whether you like the style)",
    # v2 (from the architect's notes: "doesn't look realistic", "weird scale, angle of the render"): what an
    # architect checks first, and what matters most when reviewing AI-restyled rooms.
    "realism": "believable as a real, buildable space: furniture scale fits the room, perspective and proportions "
               "are true, light and shadows behave physically; not a fake-looking render, distorted angle, or a "
               "single staged vignette that hides the room",
}
RUBRIC = "\n".join(f"- {k}: {v}" for k, v in PRINCIPLES.items())
RUBRIC_VERSION = 2

SINGLE_PROMPT = f"""You are a senior interior designer reviewing one photo for a dataset of interior design quality.

First decide what it is. Many before/after posts put BOTH photos in one image (side by side or stacked): that is
a "composite"; say how it is split and which side is the before, and score only the after side.
"render" = a 3D visualisation or AI-generated image, not a photo.
Only score real photos of a room interior (kind = interior_photo, or the after side of a composite). Otherwise
set every score and overall to 0, room_type "none", state "n/a", and leave issues and fixes empty.

Score each principle 1-5 (5 = excellent):
{RUBRIC}
overall: 1-10, judged the way an architect would. Use the full scale: a professionally styled room is NOT
automatically 8+. Reserve 8-10 for rooms that are both well designed AND believable as real spaces; pull the
score down hard for unrealistic scale or perspective, fake-looking rendering, odd lighting, or a shot that only
shows one piece of furniture instead of a room. Camera quality alone (noise, phone photo) doesn't count.
issues: the 1-3 biggest problems, concrete. fixes: one concrete fix per issue.
verdict: one sentence an architect would say."""

PAIR_PROMPT = f"""You are a senior interior designer. Image A and image B come from the same before/after post,
shown in random order.

Judge only interior DESIGN, not photo quality (camera, editing and the photo's exposure don't count; the room's
own lighting design does). Principles:
{RUBRIC}

same_room: are A and B the same room (same architecture, windows, layout), possibly redesigned?
both_interiors: are both real photos of room interiors?
better: which room is better designed ("tie" if neither). margin: 1-5, how clearly (1 = barely, 5 = night and day).
principles_improved: the principle keys the better one does clearly better. why: one or two sentences naming
the concrete differences."""

PRINCIPLE_KEYS = list(PRINCIPLES)

SINGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "composite": {"type": "string", "enum": ["none", "left_right", "top_bottom"]},
        "before_side": {"type": "string", "enum": ["none", "left", "right", "top", "bottom"]},
        "kind": {"type": "string", "enum": ["interior_photo", "exterior", "render", "floor_plan", "detail_closeup",
                                            "people_or_text", "other"]},
        "room_type": {"type": "string", "enum": ["living", "bedroom", "kitchen", "bathroom", "dining", "office", "kids",
                                                 "entry", "other", "none"]},
        "state": {"type": "string", "enum": ["empty", "under_construction", "lived_in", "staged", "designed", "n/a"]},
        "scores": {"type": "object", "properties": {k: {"type": "integer"} for k in PRINCIPLE_KEYS},
                   "required": PRINCIPLE_KEYS, "additionalProperties": False},
        "overall": {"type": "integer"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "fixes": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string"},
    },
    "required": ["composite", "before_side", "kind", "room_type", "state", "scores", "overall", "issues", "fixes",
                 "verdict"],
    "additionalProperties": False,
}

PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "same_room": {"type": "boolean"},
        "both_interiors": {"type": "boolean"},
        "better": {"type": "string", "enum": ["A", "B", "tie"]},
        "margin": {"type": "integer"},
        "principles_improved": {"type": "array", "items": {"type": "string", "enum": PRINCIPLE_KEYS}},
        "why": {"type": "string"},
    },
    "required": ["same_room", "both_interiors", "better", "margin", "principles_improved", "why"],
    "additionalProperties": False,
}

# List prices per 1M tokens (input, output) for the cost estimate printed at the end.
PRICES = {SONNET: (2.00, 10.00), INKLING: (1.87, 4.68), "gemini-3-flash-preview": (0.0, 0.0)}  # Gemini usage not tracked here


def a_is_before(pair_id: str) -> bool:
    """Fixed random order per pair (the same in the teacher run and the human labelling page)."""
    return hashlib.sha1(pair_id.encode()).digest()[0] % 2 == 0


def jpeg(path: Path) -> bytes:
    im = Image.open(path).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


# ---------------------------------------------------------------- teachers

class Sonnet:
    model = SONNET

    def __init__(self):
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY in taste/.env")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4)

    def ask(self, parts: list, prompt: str, schema: dict) -> tuple[dict | None, dict]:
        content = []
        for p in parts:
            if isinstance(p, bytes):
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.standard_b64encode(p).decode()}})
            else:
                content.append({"type": "text", "text": p})
        content.append({"type": "text", "text": prompt})
        t = time.time()
        r = self.client.beta.messages.create(
            model=SONNET, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}])
        usage = {"in": r.usage.input_tokens, "out": r.usage.output_tokens, "s": round(time.time() - t, 1),
                 "model": r.model}
        if r.stop_reason == "refusal":
            usage["refusal"] = getattr(r.stop_details, "category", None) if r.stop_details else None
            return None, usage
        text = next((b.text for b in r.content if b.type == "text"), "")
        try:
            return json.loads(text), usage
        except json.JSONDecodeError:
            return None, usage


class Gemini:
    """Gemini 3 Flash on Vertex (the backend's own client), constrained to the same JSON schema.
    Picked as the v2 teacher: closest to the human labels of everything we measured (evaluate.py)."""
    model = "gemini-3-flash-preview"

    def __init__(self):
        import sys

        sys.path.insert(0, str(ROOT.parent / "backend"))
        from app.services.three_d.vertex import generate

        self.generate = generate

    def ask(self, parts: list, prompt: str, schema: dict) -> tuple[dict | None, dict]:
        t = time.time()
        text = self.generate(self.model, [*parts, prompt], json_schema=schema, thinking="low")
        usage = {"in": 0, "out": 0, "s": round(time.time() - t, 1), "model": self.model}
        try:
            return json.loads(text.strip().removeprefix("```json").removesuffix("```")), usage
        except json.JSONDecodeError:
            return None, usage


class Inkling:
    model = INKLING

    def __init__(self):
        from openai import OpenAI

        if not os.environ.get("TINKER_API_KEY"):
            raise SystemExit("Set TINKER_API_KEY in taste/.env")
        self.client = OpenAI(base_url=TINKER_OAI, api_key=os.environ["TINKER_API_KEY"], max_retries=4, timeout=120)

    def ask(self, parts: list, prompt: str, schema: dict) -> tuple[dict | None, dict]:
        content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p).decode()}}
                   if isinstance(p, bytes) else {"type": "text", "text": p} for p in parts]
        content.append({"type": "text", "text": prompt + "\n\nReply with ONLY a JSON object matching this schema:\n"
                        + json.dumps(schema)})
        t = time.time()
        r = self.client.chat.completions.create(model=INKLING, max_tokens=1500, reasoning_effort="low", temperature=0.2,
                                                messages=[{"role": "user", "content": content}])
        usage = {"in": r.usage.prompt_tokens, "out": r.usage.completion_tokens, "s": round(time.time() - t, 1),
                 "model": INKLING}
        text = r.choices[0].message.content or ""
        start, end = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start:end + 1]), usage
        except json.JSONDecodeError:
            return None, usage


# ---------------------------------------------------------------- run

def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def run(kind: str, teacher_name: str, limit: int | None, workers: int, out: Path | None):
    teacher = {"sonnet": Sonnet, "inkling": Inkling, "gemini": Gemini}[teacher_name]()
    if kind == "singles":
        items, key = jsonl(DATA / "images.jsonl"), "id"
        out = out or DATA / "labels_singles.jsonl"
    else:
        items, key = jsonl(DATA / "pairs.jsonl"), "pair_id"
        out = out or DATA / "labels_pairs.jsonl"
    done = {r[key] for r in jsonl(out) if r.get("teacher") == teacher.model}
    todo = [i for i in items if i[key] not in done][:limit]
    print(f"{len(todo)} to label with {teacher.model} -> {out.name} ({len(done)} already done)", flush=True)
    totals = {"in": 0, "out": 0, "ok": 0, "refused": 0, "bad_json": 0, "errors": 0}
    lock = threading.Lock()

    def one(item):
        if kind == "singles":
            return item, *teacher.ask([jpeg(DATA / item["file"])], SINGLE_PROMPT, SINGLE_SCHEMA), None
        before_first = a_is_before(item["pair_id"])
        a, b = (item["before_file"], item["after_file"]) if before_first else (item["after_file"], item["before_file"])
        label, usage = teacher.ask(["Image A:", jpeg(DATA / a), "Image B:", jpeg(DATA / b)], PAIR_PROMPT, PAIR_SCHEMA)
        return item, label, usage, before_first

    with ThreadPoolExecutor(max_workers=workers) as pool, out.open("a", encoding="utf-8") as f:
        for fut in as_completed([pool.submit(one, i) for i in todo]):
            try:
                item, label, usage, before_first = fut.result()
            except Exception as e:  # one failed call shouldn't stop the run
                totals["errors"] += 1
                print("  error:", type(e).__name__, str(e)[:160], flush=True)
                continue
            totals["in"] += usage["in"]
            totals["out"] += usage["out"]
            if label is None:
                totals["refused" if "refusal" in usage else "bad_json"] += 1
                continue
            totals["ok"] += 1
            rec = {key: item[key], "teacher": teacher.model, "label": label, "usage": usage}
            if kind == "pairs":
                # Map A/B back to before/after so downstream code never has to know the order.
                rec["a_is_before"] = before_first
                winner = label["better"]
                rec["after_wins"] = None if winner == "tie" else (winner == "B") == before_first
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
    pin, pout = PRICES[teacher.model]
    cost = totals["in"] / 1e6 * pin + totals["out"] / 1e6 * pout
    print(json.dumps(totals), f"~${cost:.2f} (list price)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["singles", "pairs"])
    ap.add_argument("--teacher", choices=["sonnet", "inkling", "gemini"], default="gemini")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    run(args.kind, args.teacher, args.limit, args.workers, args.out)


if __name__ == "__main__":
    main()
