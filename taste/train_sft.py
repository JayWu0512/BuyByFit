"""LoRA SFT of Inkling 2 Small on Tinker. Runs in WSL (Inkling's renderer is Linux-only); the GPUs are Tinker's.

From PowerShell (repo root):
    wsl -d Ubuntu -- bash taste/wsl.sh train_sft.py --pilot              # 1 small step: checks setup, times it
    wsl -d Ubuntu -- bash taste/wsl.sh train_sft.py --epochs 2           # the real run

Reads data/sft_train.jsonl / sft_val.jsonl (build_sft.py). Writes data/runs/<name>/: metrics.jsonl and
checkpoints.jsonl (the tinker:// sampler path is what evaluate.py and the app use).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import tinker
from dotenv import load_dotenv
from PIL import Image

from student import COMPARE_PROMPT, IMAGE_SIDE, MODEL, REVIEW_PROMPT

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")

from tinker_cookbook import checkpoint_utils, model_info  # noqa: E402
from tinker_cookbook.image_processing_utils import get_image_processor, resize_image  # noqa: E402
from tinker_cookbook.renderers import ImagePart, Message, TextPart, TrainOnWhat, get_renderer  # noqa: E402
from tinker_cookbook.supervised.common import compute_mean_nll, datum_from_model_input_weights  # noqa: E402
from tinker_cookbook.tokenizer_utils import get_tokenizer  # noqa: E402

MAX_LENGTH = 8192


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def make_renderer():
    tokenizer = get_tokenizer(MODEL)
    image_processor = get_image_processor(MODEL)
    name = model_info.get_recommended_renderer_name(MODEL)
    return get_renderer(name, tokenizer, image_processor=image_processor, model_name=MODEL), name, tokenizer


PATCH = 40  # Inkling vision patch, px


def prep_image(path: Path) -> Image.Image:
    """Resize to <= IMAGE_SIDE with both sides at the middle of a 40 px patch (k*40 - 20).

    The local renderer and Tinker's server disagree on the token count when a side is an exact multiple of 40
    (e.g. a 1000x1000 image: 650 vs 625 tokens, and the request fails). Mid-patch sizes count the same on both.
    """
    im = resize_image(image=Image.open(path).convert("RGB"), max_size=IMAGE_SIDE)
    w, h = im.size
    fit = lambda v: max(PATCH + PATCH // 2, round(v / PATCH) * PATCH - PATCH // 2)  # noqa: E731
    return im.resize((fit(w), fit(h)), Image.Resampling.LANCZOS)


def user_message(example: dict) -> Message:
    imgs = [prep_image(DATA / f) for f in example["images"]]
    if example["task"] == "review":
        parts = [ImagePart(type="image", image=imgs[0]), TextPart(type="text", text=REVIEW_PROMPT)]
    else:
        parts = [TextPart(type="text", text="Room A:"), ImagePart(type="image", image=imgs[0]),
                 TextPart(type="text", text="Room B:"), ImagePart(type="image", image=imgs[1]),
                 TextPart(type="text", text=COMPARE_PROMPT)]
    return Message(role="user", content=parts)


def to_datum(renderer, example: dict) -> tinker.Datum:
    messages = [user_message(example),
                Message(role="assistant", content=[TextPart(type="text", text=example["target"])])]
    model_input, weights = renderer.build_supervised_example(messages=messages,
                                                             train_on_what=TrainOnWhat.LAST_ASSISTANT_MESSAGE)
    return datum_from_model_input_weights(model_input, weights, max_length=MAX_LENGTH)


def default_lr() -> float:
    try:
        from tinker_cookbook.hyperparam_utils import get_lr
        return float(get_lr(MODEL))
    except Exception:
        return 2e-4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=time.strftime("sft-%m%d-%H%M"))
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--eval-every", type=int, default=10)
    ap.add_argument("--pilot", action="store_true", help="one step of 4 examples, then stop")
    args = ap.parse_args()

    train, val = jsonl(DATA / "sft_train.jsonl"), jsonl(DATA / "sft_val.jsonl")
    if not train:
        raise SystemExit("No data/sft_train.jsonl: run build_sft.py first")
    lr = args.lr or default_lr()
    bs = 4 if args.pilot else args.batch_size
    steps = 1 if args.pilot else max(1, int(math.ceil(len(train) * args.epochs / bs)))
    run_dir = DATA / "runs" / (args.name + ("-pilot" if args.pilot else ""))
    run_dir.mkdir(parents=True, exist_ok=True)

    renderer, renderer_name, tokenizer = make_renderer()
    print(f"model {MODEL} · renderer {renderer_name} · {len(train)} train / {len(val)} val · "
          f"batch {bs} · {steps} steps · lr {lr:g} · rank {args.rank}", flush=True)

    t0 = time.time()
    service = tinker.ServiceClient()
    trainer = service.create_lora_training_client(base_model=MODEL, rank=args.rank).result()
    print(f"training client ready in {time.time() - t0:.1f}s", flush=True)

    rng = random.Random(0)
    order = []
    while len(order) < steps * bs:
        order += rng.sample(range(len(train)), len(train))
    val_batch = [to_datum(renderer, ex) for ex in val[:32]] if val and not args.pilot else []
    log = (run_dir / "metrics.jsonl").open("a")

    for step in range(steps):
        t = time.time()
        examples = [train[i] for i in order[step * bs:(step + 1) * bs]]
        batch = [to_datum(renderer, ex) for ex in examples]
        t_build = time.time() - t
        cur_lr = lr * (1 - step / steps)  # linear decay
        fb = trainer.forward_backward(batch, loss_fn="cross_entropy")
        opt = trainer.optim_step(tinker.AdamParams(learning_rate=cur_lr, beta1=0.9, beta2=0.95, eps=1e-8))
        fb_res = fb.result()
        opt.result()
        nll = compute_mean_nll([x["logprobs"] for x in fb_res.loss_fn_outputs],
                               [d.loss_fn_inputs["weights"] for d in batch])
        m = {"step": step, "train_nll": round(float(nll), 4), "lr": cur_lr,
             "tokens": sum(d.model_input.length for d in batch), "build_s": round(t_build, 1),
             "step_s": round(time.time() - t, 1)}
        if val_batch and (step % args.eval_every == 0 or step == steps - 1):
            res = trainer.forward(val_batch, loss_fn="cross_entropy").result()
            m["val_nll"] = round(float(compute_mean_nll([x["logprobs"] for x in res.loss_fn_outputs],
                                                        [d.loss_fn_inputs["weights"] for d in val_batch])), 4)
        log.write(json.dumps(m) + "\n")
        log.flush()
        print(json.dumps(m), flush=True)
        if not args.pilot and step and step % 20 == 0:
            checkpoint_utils.save_checkpoint(training_client=trainer, name=f"{step:05d}", log_path=str(run_dir),
                                             kind="sampler", loop_state={"step": step}, ttl_seconds=7 * 86400)  # sampler only: full state is ~47 GB and fills free storage

    if args.pilot:
        s = m["step_s"]
        print(f"\nPILOT OK. One step of {bs} examples ({m['tokens']} tokens) took {s}s "
              f"(+{time.time() - t0 - s:.0f}s setup). Rough full run at batch {args.batch_size}: "
              f"{math.ceil(len(train) * args.epochs / args.batch_size)} steps.", flush=True)
        return
    checkpoint_utils.save_checkpoint(training_client=trainer, name="final", log_path=str(run_dir), kind="sampler",
                                     loop_state={"step": steps}, ttl_seconds=None)
    print(f"done in {(time.time() - t0) / 60:.1f} min. Checkpoints: {run_dir / 'checkpoints.jsonl'}", flush=True)


if __name__ == "__main__":
    main()
