"""What the student (Inkling 2 Small) sees and says. Shared by build_sft.py, train_sft.py, evaluate.py and the app.

Two tasks, one model:
  review   one room photo  -> {"overall", "scores", "issues", "fixes", "verdict"}
  compare  photos A and B  -> {"better": "A"|"B"|"tie", "why"}
The prompts stay short and fixed: the model learns the rubric from the examples, not from a long instruction.
"""
from __future__ import annotations

import json
import re

MODEL = "thinkingmachines/Inkling-2-Small"
IMAGE_SIDE = 1024  # px; enough to judge design, keeps image tokens (and cost) down

PRINCIPLES = ["scale", "layout", "focal_point", "lighting", "palette", "restraint", "cohesion", "realism"]

REVIEW_PROMPT = (
    "You are an interior design reviewer. Judge this room's DESIGN (not the photo). Reply with JSON: "
    '{"overall": 1-10, "scores": {' + ", ".join(f'"{p}": 1-5' for p in PRINCIPLES) + '}, '
    '"issues": [...], "fixes": [...], "verdict": "..."}'
)

COMPARE_PROMPT = (
    "You are an interior design reviewer. Which room is better DESIGNED, A or B? Ignore photo quality. "
    'Reply with JSON: {"better": "A" | "B" | "tie", "why": "..."}'
)


def review_target(label: dict) -> str:
    # v1 labels have no "realism" (added in rubric v2): leave out whatever a label doesn't have.
    out = {"overall": label["overall"], "scores": {p: label["scores"][p] for p in PRINCIPLES if p in label["scores"]},
           "issues": label["issues"][:3], "fixes": label["fixes"][:3], "verdict": label["verdict"]}
    return json.dumps(out, ensure_ascii=False)


def compare_target(better: str, why: str) -> str:
    return json.dumps({"better": better, "why": why}, ensure_ascii=False)


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
