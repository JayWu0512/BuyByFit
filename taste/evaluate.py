"""Score models against YOUR labels (data/labels_human.jsonl), and against the posts' own before/after truth.

    uv run python evaluate.py base                         # untuned Inkling 2 Small
    uv run python evaluate.py tinker://...sampler_weights  # a fine-tuned checkpoint (from checkpoints.jsonl)
    uv run python evaluate.py latest                       # newest checkpoint under data/runs/
    uv run python evaluate.py teacher                      # Sonnet's labels (no API calls)

Metrics:
  singles  Spearman rank correlation of the model's 1-10 score with yours (1.0 = same ranking), and mean error
  pairs    agreement with your pick on pairs you didn't call a tie or different rooms
  val      held-out before/after pairs (data/sft_val.jsonl): does it pick the post's "after"?
Runs on Windows through Tinker's OpenAI-compatible API. Results are appended to data/eval_results.jsonl.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

from student import COMPARE_PROMPT, IMAGE_SIDE, MODEL, REVIEW_PROMPT, parse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")
TINKER_OAI = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def latest_human() -> dict[str, dict]:
    out = {}
    for r in jsonl(DATA / "labels_human.jsonl"):
        out[r["item_id"]] = r
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(cov / (sx * sy), 3) if sx and sy else None


# ---------------------------------------------------------------- model calls

class Student:
    def __init__(self, model: str):
        from openai import OpenAI

        if not os.environ.get("TINKER_API_KEY"):
            raise SystemExit("Set TINKER_API_KEY in taste/.env")
        self.model = model
        self.client = OpenAI(base_url=TINKER_OAI, api_key=os.environ["TINKER_API_KEY"], max_retries=4, timeout=180)

    @staticmethod
    def image(path: Path) -> dict:
        im = Image.open(path).convert("RGB")
        im.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}

    def ask(self, content: list) -> dict | None:
        # reasoning_effort="none" is not honoured by Inkling 2 Small (it still reasons and runs out of tokens);
        # "low" with room for the JSON works. Same settings for base and tuned models, so the comparison is fair.
        r = self.client.chat.completions.create(model=self.model, max_tokens=2500, temperature=0.0,
                                                reasoning_effort="low",
                                                messages=[{"role": "user", "content": content}])
        return parse(r.choices[0].message.content or "")

    def review(self, file: str) -> dict | None:
        return self.ask([self.image(DATA / file), {"type": "text", "text": REVIEW_PROMPT}])

    def compare(self, a: str, b: str) -> dict | None:
        return self.ask([{"type": "text", "text": "Room A:"}, self.image(DATA / a),
                         {"type": "text", "text": "Room B:"}, self.image(DATA / b),
                         {"type": "text", "text": COMPARE_PROMPT}])


GEMINI = {"gemini-flash": "gemini-3-flash-preview", "gemini-pro": "gemini-3.1-pro-preview"}


class GeminiStudent:
    """Same prompts and images as Student, sent to Gemini on Vertex through the backend's own client."""

    def __init__(self, model: str):
        sys.path.insert(0, str(ROOT.parent / "backend"))
        from app.services.three_d.vertex import generate  # noqa: E402

        self.model, self.generate = model, generate

    @staticmethod
    def jpeg(path: Path) -> bytes:
        im = Image.open(path).convert("RGB")
        im.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue()

    def ask(self, parts: list) -> dict | None:
        try:
            return parse(self.generate(self.model, parts, thinking="low"))
        except Exception as e:
            print("  gemini error:", str(e)[:120], flush=True)
            return None

    def review(self, file: str) -> dict | None:
        return self.ask([self.jpeg(DATA / file), REVIEW_PROMPT])

    def compare(self, a: str, b: str) -> dict | None:
        return self.ask(["Room A:", self.jpeg(DATA / a), "Room B:", self.jpeg(DATA / b), COMPARE_PROMPT])


def resolve(target: str) -> str:
    if target == "base":
        return MODEL
    if target == "latest":
        found = []
        for f in (DATA / "runs").glob("*/checkpoints.jsonl"):
            for r in jsonl(f):
                path = next((v for k, v in r.items() if "sampler" in k and isinstance(v, str)), None)
                if path:
                    found.append((f.stat().st_mtime, r.get("name", ""), path))
        if not found:
            sys.exit("No checkpoints under data/runs/")
        found.sort()
        print("latest checkpoint:", found[-1][2])
        return found[-1][2]
    return target


# ---------------------------------------------------------------- run

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="base | latest | teacher | gemini-flash | gemini-pro | tinker://... sampler path")
    ap.add_argument("--architect", action="store_true", help="also score the architect's 10 rooms")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-val", action="store_true")
    args = ap.parse_args()

    sample = {s["item_id"]: s for s in jsonl(DATA / "human_sample.jsonl")}
    human = latest_human()
    singles = [(s, human[i]) for i, s in sample.items() if s["type"] == "single" and i in human
               and not human[i].get("skip") and human[i].get("overall")]
    pairs = [(s, human[i]) for i, s in sample.items() if s["type"] == "pair" and i in human
             and not human[i].get("skip") and human[i].get("same_room", True) and human[i].get("better") in ("A", "B")]
    arch = {r["item_id"]: r["overall"] for r in jsonl(DATA / "labels_expert.jsonl")} if args.architect else {}
    arch_ids = [i for i in arch if i in sample]
    val = [] if args.no_val else jsonl(DATA / "sft_val.jsonl")
    val_pairs = [r for r in val if r["task"] == "compare"]
    val_reviews = [r for r in val if r["task"] == "review"]
    print(f"human: {len(singles)} singles, {len(pairs)} decisive pairs · val: {len(val_reviews)} reviews, "
          f"{len(val_pairs)} pairs", flush=True)

    if args.target == "teacher":
        t_single = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
        t_pair = {r["pair_id"]: r for r in jsonl(DATA / "labels_pairs.jsonl")}
        single_preds = [(t_single.get(s["item_id"], {}).get("overall"), h["overall"]) for s, h in singles]
        pair_preds = []
        for s, h in pairs:
            t = t_pair.get(s["item_id"])
            # The teacher saw the same fixed A/B order as the labelling page (label.a_is_before).
            pair_preds.append((t["label"]["better"] if t else None, h["better"]))
        val_preds, val_rev = [], []
        arch_preds = [(t_single.get(i, {}).get("overall"), arch[i]) for i in arch_ids]
        model_name = "teacher (Sonnet 5.5 labels)"
    else:
        if args.target in GEMINI:
            model_name = GEMINI[args.target]
            st = GeminiStudent(model_name)
        else:
            model_name = resolve(args.target)
            st = Student(model_name)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            single_out = list(pool.map(lambda sh: (st.review(sh[0]["a"]) or {}), singles))
            pair_out = list(pool.map(lambda sh: (st.compare(sh[0]["a"], sh[0]["b"]) or {}), pairs))
            val_out = list(pool.map(lambda r: (st.compare(*r["images"]) or {}), val_pairs))
            val_rev_out = list(pool.map(lambda r: (st.review(r["images"][0]) or {}), val_reviews))
            arch_out = list(pool.map(lambda i: (st.review(sample[i]["a"]) or {}), arch_ids))
        arch_preds = [(o.get("overall"), arch[i]) for o, i in zip(arch_out, arch_ids)]
        single_preds = [(o.get("overall"), h["overall"]) for o, (s, h) in zip(single_out, singles)]
        pair_preds = [(o.get("better"), h["better"]) for o, (s, h) in zip(pair_out, pairs)]
        val_preds = [(o.get("better"), json.loads(r["target"])["better"]) for o, r in zip(val_out, val_pairs)]
        val_rev = [(o.get("overall"), json.loads(r["target"])["overall"]) for o, r in zip(val_rev_out, val_reviews)]

    ok_s = [(p, h) for p, h in single_preds if isinstance(p, (int, float)) and 1 <= p <= 10]
    ok_v = [(p, t) for p, t in val_rev if isinstance(p, (int, float)) and 1 <= p <= 10]
    ok_a = [(p, t) for p, t in arch_preds if isinstance(p, (int, float)) and 1 <= p <= 10]
    res = {"model": model_name,
           "singles_n": len(singles), "singles_parsed": len(ok_s),
           "singles_spearman": spearman([p for p, _ in ok_s], [h for _, h in ok_s]),
           "singles_mae": round(sum(abs(p - h) for p, h in ok_s) / len(ok_s), 2) if ok_s else None,
           "pairs_n": len(pairs),
           "pairs_agree": round(sum(p == h for p, h in pair_preds) / len(pairs), 3) if pairs else None,
           "architect_n": len(ok_a),
           "architect_spearman": spearman([p for p, _ in ok_a], [t for _, t in ok_a]),
           "architect_mean": round(sum(p for p, _ in ok_a) / len(ok_a), 1) if ok_a else None,
           "val_reviews_n": len(val_rev), "val_reviews_parsed": len(ok_v),
           "val_spearman_vs_teacher": spearman([p for p, _ in ok_v], [t for _, t in ok_v]),
           "val_mae_vs_teacher": round(sum(abs(p - t) for p, t in ok_v) / len(ok_v), 2) if ok_v else None,
           "val_pairs_n": len(val_preds),
           "val_after_acc": round(sum(p == t for p, t in val_preds) / len(val_preds), 3) if val_preds else None}
    print(json.dumps(res, indent=1))
    with (DATA / "eval_results.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
