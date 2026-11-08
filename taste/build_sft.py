"""Build the SFT dataset from teacher labels, keeping the human eval set (and its pages) out.

    uv run python build_sft.py      # -> data/sft_train.jsonl, data/sft_val.jsonl, prints the mix

Review examples: every image Sonnet called a real interior photo (for composites, the split "after" half, which is
the side Sonnet scored). Compare examples: same-room before/after pairs; the winner is the post's own "after"
(ground truth), shown at random A/B position; the "why" comes from Sonnet only when Sonnet also picked the after
(otherwise a generic reason would teach nothing, so the pair is skipped).
Split by PAGE, so photos of the same room never sit on both sides. 10% of pages go to validation.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from student import compare_target, review_target

DATA = Path(__file__).resolve().parent / "data"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def page_bucket(page_url: str) -> float:
    return hashlib.sha1(page_url.encode()).digest()[0] / 256


def main():
    images = {r["id"]: r for r in jsonl(DATA / "images.jsonl")}
    singles = {r["id"]: r["label"] for r in jsonl(DATA / "labels_singles.jsonl")}
    pairs = {p["pair_id"]: p for p in jsonl(DATA / "pairs.jsonl")}
    pair_labels = {r["pair_id"]: r for r in jsonl(DATA / "labels_pairs.jsonl")}
    sample = jsonl(DATA / "human_sample.jsonl")
    if not sample:
        print("WARNING: no human_sample.jsonl yet -> nothing is held out for the human eval. "
              "Run `label_ui.py sample` first.")
    # Hold out the human-eval photos themselves (both photos of each eval pair), not whole pages: with ~100 pages,
    # page-level holdout left ~10% of the data. Known caveat: another photo of the same room from the same page can
    # still be in training, so human-eval numbers are slightly optimistic.
    held_files = set()
    for s in sample:
        held_files.add(s["a"])
        if s.get("b"):
            held_files.add(s["b"])
    held_ids = {s["item_id"] for s in sample}
    for p in pairs.values():
        if p["pair_id"] in held_ids:
            held_files |= {p["before_file"], p["after_file"], images.get(p["before"], {}).get("file", ""),
                           images.get(p["after"], {}).get("file", "")}
    held_files.discard("")

    rng = random.Random(0)
    train, val = [], []
    n_held = 0

    def put(example, page_url):
        nonlocal n_held
        files = set(example["images"])
        if example["id"] in held_ids or files & held_files:
            n_held += 1
            return
        (val if page_bucket(page_url) < 0.10 else train).append(example)

    n_review = n_compare = 0
    for img_id, label in singles.items():
        rec = images.get(img_id)
        if not rec or label.get("overall", 0) < 1:
            continue
        if label.get("composite") in ("left_right", "top_bottom"):
            file = f"split/{img_id}_after.jpg"
            if not (DATA / file).exists():
                continue
        elif label.get("kind") == "interior_photo":
            file = rec["file"]
        else:
            continue
        if rec["file"] in held_files:  # a composite whose original image is in the eval
            continue
        put({"task": "review", "images": [file], "target": review_target(label), "id": img_id}, rec["page_url"])
        n_review += 1

    for pid, pl in pair_labels.items():
        p = pairs.get(pid)
        lab = pl["label"]
        if not p or not lab.get("same_room") or not lab.get("both_interiors") or pl.get("after_wins") is not True:
            continue
        after_first = rng.random() < 0.5
        files = [p["after_file"], p["before_file"]] if after_first else [p["before_file"], p["after_file"]]
        better = "A" if after_first else "B"
        put({"task": "compare", "images": files, "target": compare_target(better, lab["why"]), "id": pid},
            p["page_url"])
        n_compare += 1

    rng.shuffle(train)
    for name, rows in (("sft_train.jsonl", train), ("sft_val.jsonl", val)):
        with (DATA / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    count = lambda rows, t: sum(1 for r in rows if r["task"] == t)  # noqa: E731
    print(f"review {n_review}, compare {n_compare} usable; {n_held} held out for the human eval "
          f"({len(held_files)} photos)")
    print(f"train: {len(train)} ({count(train, 'review')} review, {count(train, 'compare')} compare)")
    print(f"val:   {len(val)} ({count(val, 'review')} review, {count(val, 'compare')} compare)")


if __name__ == "__main__":
    main()
