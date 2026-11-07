# Room designer: scan a room, say a vibe, get it furnished

Open **`/room`** on the AR MVP server (`python ar-mvp/server.py`).

```text
scan ─┬─ iPhone Pro LiDAR (Polycam / 3D Scanner App → export .glb or .obj)  → sample surface points (metric)
      └─ any phone video (20–30 s, slow walk-around)  → VGGT on the GPU → points + camera path (needs setup, below)
   → analyze.py: floor plane → level + metric scale → square to walls → 5 cm grid of free floor + existing furniture
vibe → planner.py (rules, no LLM): room type → slots → pose rules → vector search with size limits → real-footprint fit
   → 3D viewer: your room + placed products, a reason for each, swap among items that fit the same spot, before/after
```

## Try it without a scan

Click **Try a demo room**, or open `/room?demo=living&vibe=cozy mid-century with plants`
(`demo=bedroom` is a room that already has a bed).

## Scanning

| Phone | How | Scale |
|---|---|---|
| iPhone / iPad **Pro** (LiDAR) | Polycam or 3D Scanner App, room/LiDAR mode → export **GLB** (or OBJ) → upload | exact (metres) |
| Anything else | record a slow 20–30 s video walking around the room, phone held at chest height, mostly pointing at the floor and walls → upload | from the phone's height above the floor (~1.4 m); type the longest wall's length for exact scale |

**Video needs a one-time setup** (CUDA PyTorch + VGGT, about 8 GB). It's in its own venv so the search server stays untouched:

```powershell
powershell -ExecutionPolicy Bypass -File ar-mvp\room\setup_video_recon.ps1
```

Needs an NVIDIA GPU (tested target: RTX 4060 8 GB, which takes 20 frames). The VGGT-1B weights are licensed for non-commercial use.

## How the planner decides (rules)

- **Room type:** from your words ("bedroom", "office", "nursery"), otherwise from the scan (a bed-sized object means a bedroom), otherwise a living room.
- **Templates:**
  - living: sofa → rug → coffee table → floor lamp → side table → armchair → planter
  - bedroom: bed → 2 nightstands → table lamp → rug → dresser → planter
  - office: desk → chair → shelf → lamp → planter → rug
  - nursery: rug → bean bag → shelf → 3 plushies → lamp → planter
- **Vibe modifiers:**
  - *cute/kawaii/playful* adds plushies and a pillow (and a bean bag in big rooms)
  - *cozy/warm* adds pillows and makes sure there's a rug
  - *plants/boho/jungle* adds planters
  - *minimal/japandi/zen* trims the room to 4 pieces
  - rooms under 8 m² drop the extras
- **Placement rules:**
  - big pieces go against the longest clear wall, facing into the room
  - the rug goes half under the sofa's front (or the bed's foot), long side along it
  - the coffee table sits 45 cm in front of the sofa
  - the lamp, side table and nightstands go at the ends
  - the armchair sits at the side, facing the middle
  - plants and bean bags go in the emptiest corner
  - pillows and plushies sit on the sofa or bed, and the table lamp on a nightstand
- **Existing furniture:** a scanned sofa or bed is kept, and the plan builds around it.
- **Fit:**
  - a product's real footprint comes from its 3D model's bounding box, not the listing
  - it must land on floor the scan actually saw, with nothing already there (5 cm grid)
  - the swap buttons only offer products that fit that same spot

## Files

| File | What |
|---|---|
| `analyze.py` | floor RANSAC, levelling, scale, wall alignment, occupancy grid, existing-furniture blobs |
| `planner.py` | templates, vibe modifiers, pose rules, product picking, reasons |
| `ingest.py` | LiDAR mesh → points; video recon `.npz` → points |
| `recon_vggt.py` | video → frames (sharpest per slice) → VGGT → points + camera path (runs in the GPU venv) |
| `glb_bounds.py` | model bounding boxes read straight from the GLB JSON (works with Draco) |
| `room_api.py` | `/api/room/upload`, `/api/room/demo`, `/api/room/{id}`, `/api/room/{id}/plan`, `/rooms/{id}/…` |
| `demo_room.py`, `test_room.py` | synthetic rooms; tests check measurement, scale recovery, no overlaps, bed detection |

Room data is kept in `%USERPROFILE%\buybyfit-data\rooms\<id>\` (outside the repo).
