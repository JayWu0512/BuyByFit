"""A teacher that scores like YOU: Sonnet 5.5 sees ~20 of your scored rooms (with notes) before every judgement.

    uv run python calibrate.py test            # score your OTHER labelled rooms; compare with you vs plain Sonnet
    uv run python calibrate.py label           # relabel every image -> data/labels_singles_calibrated.jsonl

The examples are a cached prompt prefix (prompt caching), so ~20 extra images cost ~0.1x after the first call.
Your labelled rooms are split once (fixed seed): "shots" are shown to the teacher, "holdout" is only used to
measure it, and stays the human eval for the student too.
"""
from __future__ import annotations

import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from label import DATA, PRINCIPLES, RUBRIC, SINGLE_SCHEMA, SONNET, Sonnet, jpeg, jsonl

SPLIT = DATA / "human_split.json"
N_SHOTS = 20

INTRO = f"""You are scoring interior design quality for one specific design lead. Their standards are stricter
and more discriminating than a typical reviewer's: a professionally styled room is NOT automatically an 8;
generic, safe, builder-grade or over-decorated "designed" rooms can score low. Learn their scale and taste from
the scored examples below (their score, the weak spots they ticked, and their notes), then score new rooms the
way THEY would. Use their scale, not your own.

Principles (1-5 each):
{RUBRIC}

Here are rooms they scored:"""

TASK = """Now score this new room the way this design lead would (their 1-10 scale, as in the examples).
Follow the same output rules as before: decide kind/composite first; only score real interior photos (or the
after side of a composite); otherwise all scores and overall = 0, room_type "none", state "n/a"."""


def human_singles() -> dict[str, dict]:
    latest = {}
    for r in jsonl(DATA / "labels_human.jsonl"):
        latest[r["item_id"]] = r
    sample = {s["item_id"]: s for s in jsonl(DATA / "human_sample.jsonl")}
    out = {}
    for i, h in latest.items():
        s = sample.get(i)
        if s and s["type"] == "single" and not h.get("skip") and h.get("overall"):
            out[i] = {**h, "file": s["a"]}
    return out


def split() -> dict:
    if SPLIT.exists():
        return json.loads(SPLIT.read_text())
    hs = human_singles()
    rng = random.Random(11)
    ids = sorted(hs)
    rng.shuffle(ids)
    # Shots: spread over your score range, notes preferred; the rest is the holdout.
    by_score: dict[int, list[str]] = {}
    for i in sorted(ids, key=lambda i: not hs[i].get("note")):
        by_score.setdefault(hs[i]["overall"], []).append(i)
    shots = []
    while len(shots) < min(N_SHOTS, len(ids) // 2) and any(by_score.values()):
        for sc in sorted(by_score):
            if by_score[sc] and len(shots) < min(N_SHOTS, len(ids) // 2):
                shots.append(by_score[sc].pop(0))
    holdout = [i for i in ids if i not in shots]
    sp = {"shots": shots, "holdout": holdout}
    SPLIT.write_text(json.dumps(sp, indent=1))
    return sp


def prefix(shots: list[str]) -> list[dict]:
    """The cached part of every request: intro + each example image with the design lead's verdict."""
    import base64

    hs = human_singles()
    content: list[dict] = [{"type": "text", "text": INTRO}]
    for n, i in enumerate(shots, 1):
        h = hs[i]
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(jpeg(DATA / h["file"])).decode()}})
        weak = ", ".join(h.get("weak") or []) or "none ticked"
        note = (h.get("note") or "").strip() or "(no note)"
        content.append({"type": "text", "text": f"Example {n}: their score {h['overall']}/10. Weak spots: {weak}. "
                                                f"Note: {note}"})
    content[-1]["cache_control"] = {"type": "ephemeral"}
    return content


class Calibrated(Sonnet):
    def __init__(self, shots):
        super().__init__()
        self.prefix = prefix(shots)

    def score(self, file: Path) -> tuple[dict | None, dict]:
        import base64

        content = self.prefix + [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(jpeg(file)).decode()}},
            {"type": "text", "text": TASK}]
        t = time.time()
        r = self.client.beta.messages.create(
            model=SONNET, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SINGLE_SCHEMA}},
            messages=[{"role": "user", "content": content}])
        u = r.usage
        usage = {"in": u.input_tokens, "out": u.output_tokens, "cache_read": u.cache_read_input_tokens or 0,
                 "cache_write": u.cache_creation_input_tokens or 0, "s": round(time.time() - t, 1)}
        if r.stop_reason == "refusal":
            return None, {**usage, "refusal": True}
        text = next((b.text for b in r.content if b.type == "text"), "")
        try:
            return json.loads(text), usage
        except json.JSONDecodeError:
            return None, usage


def cost(usages: list[dict]) -> float:
    # Sonnet 5.5: $2/M input, $10/M output, cache writes 1.25x input, cache reads $0.20/M.
    return sum(u["in"] * 2 + u["out"] * 10 + u["cache_write"] * 2.5 + u["cache_read"] * 0.2 for u in usages) / 1e6


def run(items: list[tuple[str, Path]], teacher: Calibrated, workers: int, sink=None) -> dict:
    results, usages = {}, []
    lock = threading.Lock()
    if not items:
        return results
    # One call first, so the shared prefix is cached before the parallel calls arrive.
    first, rest = items[0], items[1:]
    lab, u = teacher.score(first[1])
    usages.append(u)
    results[first[0]] = lab
    if sink and lab:
        sink(first[0], lab, u)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(teacher.score, f): i for i, f in rest}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                lab, u = fut.result()
            except Exception as e:
                print("  error:", type(e).__name__, str(e)[:120], flush=True)
                continue
            with lock:
                usages.append(u)
                results[i] = lab
                if sink and lab:
                    sink(i, lab, u)
    print(f"{len(usages)} calls · cache read {sum(u['cache_read'] for u in usages):,} tok · ~${cost(usages):.2f}",
          flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["test", "label"])
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    sp = split()
    print(f"{len(sp['shots'])} shots, {len(sp['holdout'])} held out", flush=True)
    teacher = Calibrated(sp["shots"])

    if args.cmd == "test":
        from evaluate import spearman

        hs = human_singles()
        plain = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
        res = run([(i, DATA / hs[i]["file"]) for i in sp["holdout"]], teacher, args.workers)
        rows = [(hs[i]["overall"], (res.get(i) or {}).get("overall"), plain.get(i, {}).get("overall"))
                for i in sp["holdout"]]
        rows = [r for r in rows if isinstance(r[1], int) and r[1] > 0 and isinstance(r[2], int) and r[2] > 0]
        you, cal, pl = zip(*rows)
        mae = lambda a, b: round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 2)  # noqa: E731
        print(json.dumps({"n": len(rows), "your_mean": round(sum(you) / len(you), 1),
                          "plain_sonnet": {"spearman": spearman(list(pl), list(you)), "mae": mae(pl, you),
                                           "mean": round(sum(pl) / len(pl), 1)},
                          "calibrated_sonnet": {"spearman": spearman(list(cal), list(you)), "mae": mae(cal, you),
                                                "mean": round(sum(cal) / len(cal), 1)}}, indent=1))
        return

    out = DATA / "labels_singles_calibrated.jsonl"
    done = {r["id"] for r in jsonl(out)}
    images = [r for r in jsonl(DATA / "images.jsonl") if r["id"] not in done]
    print(f"{len(images)} images to label ({len(done)} done)", flush=True)
    f = out.open("a", encoding="utf-8")

    def sink(i, lab, u):
        f.write(json.dumps({"id": i, "teacher": SONNET + "+calibrated", "label": lab, "usage": u}) + "\n")
        f.flush()

    run([(r["id"], DATA / r["file"]) for r in images], teacher, args.workers, sink)
    f.close()


if __name__ == "__main__":
    main()
