"""Which teacher scores most like the humans? Run before relabelling everything.

    uv run --with google-auth python rubric_test.py --teacher gemini
    uv run python rubric_test.py --teacher sonnet

Scores the architect's 10 + your labelled singles with the current rubric (label.py), compares with the v1 labels,
and with the average of every teacher already tested (data/rubric_test.jsonl). Writes nothing to label files.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from evaluate import spearman
from label import DATA, RUBRIC_VERSION, SINGLE_PROMPT, SINGLE_SCHEMA, Gemini, Sonnet, jpeg, jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", choices=["sonnet", "gemini"], default="gemini")
    args = ap.parse_args()

    sample = {s["item_id"]: s for s in jsonl(DATA / "human_sample.jsonl")}
    you = {}
    for r in jsonl(DATA / "labels_human.jsonl"):
        you[r["item_id"]] = r
    you = {i: r["overall"] for i, r in you.items() if not r.get("skip") and r.get("overall")
           and sample.get(i, {}).get("type") == "single"}
    arch = {r["item_id"]: r["overall"] for r in jsonl(DATA / "labels_expert.jsonl")}
    ids = sorted(set(you) | set(arch))
    teacher = Sonnet() if args.teacher == "sonnet" else Gemini()

    def one(i):
        try:
            lab, usage = teacher.ask([jpeg(DATA / sample[i]["a"])], SINGLE_PROMPT, SINGLE_SCHEMA)
        except Exception as e:
            print("  error:", str(e)[:120], flush=True)
            lab, usage = None, {}
        return i, lab, usage

    with ThreadPoolExecutor(6) as pool:
        out = list(pool.map(one, ids))
    with (DATA / "rubric_test.jsonl").open("a", encoding="utf-8") as f:
        for i, lab, usage in out:
            f.write(json.dumps({"id": i, "rubric": RUBRIC_VERSION, "teacher": teacher.model, "label": lab,
                                "usage": usage}) + "\n")

    # Every teacher tested on the current rubric (old rows without "teacher" were Sonnet).
    by_teacher: dict[str, dict[str, int]] = {}
    for r in jsonl(DATA / "rubric_test.jsonl"):
        ov = (r.get("label") or {}).get("overall")
        if r.get("rubric") == RUBRIC_VERSION and isinstance(ov, int) and ov > 0:
            by_teacher.setdefault(r.get("teacher", "claude-sonnet-5-5"), {})[r["id"]] = ov
    if len(by_teacher) >= 2:
        names = sorted(by_teacher)
        common = set.intersection(*(set(v) for v in by_teacher.values()))
        by_teacher["average of " + " + ".join(n.split("-")[0] for n in names)] = {
            i: sum(by_teacher[n][i] for n in names) / len(names) for i in common}

    for who, human in (("you", you), ("architect", arch)):
        print(f"\n{who} (mean {round(sum(human.values()) / len(human), 1)}):")
        for name, scores in by_teacher.items():
            rows = [(human[i], scores[i]) for i in human if i in scores]
            if len(rows) < 3:
                continue
            h, s = zip(*rows)
            mae = round(sum(abs(a - b) for a, b in rows) / len(rows), 2)
            print(f"  {name:40s} n={len(rows):2d}  spearman {spearman(list(s), list(h))}  mae {mae}  "
                  f"mean {round(sum(s) / len(s), 1)}")


if __name__ == "__main__":
    main()
