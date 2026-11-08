# Taste model: an interior design reviewer fine-tuned on Tinker

Goal: a vision model (Inkling 2 Small, fine-tuned on Tinker) that judges interior **design** quality the way a
designer would, and says why. Data: before/after posts from small studios, stagers and restoration firms.

## Setup

```powershell
cd taste
uv sync
# taste/.env (gitignored):
#   ANTHROPIC_API_KEY=...   teacher labels (Claude Sonnet 5.5)
#   TINKER_API_KEY=...      Inkling teacher (optional) and training
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
