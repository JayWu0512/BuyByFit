# Taste model: interior-design review research

> Status: training and evaluation tooling for the optional fine-tuned interior
> expert used by the room-visualization pipeline. It is not a standalone
> customer-facing service, and its output must not be represented as an
> automated guarantee of design quality.

Goal: evaluate whether a fine-tuned vision model can judge interior-design
quality in a designer-like way and explain its reasoning. Source material is
before/after posts from small studios, stagers, and restoration firms.

## Setup

```powershell
cd taste
uv sync
# taste/.env (gitignored):
#   ANTHROPIC_API_KEY=...   teacher-label provider
#   TINKER_API_KEY=...      optional training provider
```

## Pipeline

| Step | Command | What it does |
|---|---|---|
| 1. Scrape | `uv run python scrape.py seeds.txt` | Polite crawl (robots.txt, 2 s/request/site) -> `data/raw/`, `data/images.jsonl` |
| 2. Teacher: singles | `uv run python label.py singles` | Sonnet 5.5: interior or not, composite split, 7 principle scores, overall, issues, fixes (~$10 / 1,000 images) |
| 3. Pairs | `uv run python pairs.py` | Before/after pairs: labelled, page candidates, split composites; `data/gallery.html` to browse |
| 4. Teacher: pairs | `uv run python label.py pairs` | Same room? Which is better designed? Why? (A/B order randomised) |
| 5. Human sample | `uv run python label_ui.py sample --n 100` | 100 items spread across sites (40% pairs) -> `data/human_sample.jsonl` |
| 6. Label | `uv run python label_ui.py serve` | http://127.0.0.1:8765, keyboard-driven; teacher labels are hidden -> `data/labels_human.jsonl` |

Run `pairs.py` again after step 4 to see the teacher's verdicts in the gallery.

## Labelling keys

Singles: `1`-`9`, `0` = 10 design score · `q w e r t y u` toggle weak spots (scale, layout, focal point, lighting,
palette, restraint, cohesion) · `Enter` save & next · `x` skip (not a usable interior) · `n` note · `←` `→` move.
Pairs: `a` / `b` / `t` better or tie · `1`-`5` by how much · `d` different rooms · `Enter` save & next.

Judge the room's design, not the photo (camera, editing, exposure don't count).

## The rubric

scale · layout (circulation, use) · focal point · lighting (layered) · palette (colour and materials) ·
restraint (no clutter) · cohesion (does ITS style well; style preference doesn't count). See `PRINCIPLES` in
`label.py`.

## Data rules

`data/` is gitignored and stays private: images are other people's work, used for hackathon research only, never
redistributed, deleted after the event. Every record keeps its source page URL.
