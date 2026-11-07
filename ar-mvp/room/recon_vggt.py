"""Phone video -> 3D point cloud of the room, with VGGT (facebookresearch/vggt) on the GPU.

Runs in its own venv (see setup_video_recon.ps1), called by the server as a subprocess:
    <venv>/python recon_vggt.py room.mp4 out.npz [--frames 20]

Picks the sharpest frame in each of N even time slices, runs VGGT once over all of them, unprojects
depth into world points, keeps the confident half, and saves points + colors + camera path.
VGGT output has no absolute scale; analyze.py fixes that from the camera height (or a known width).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import torch


def pick_frames(video: Path, n: int, out_dir: Path) -> list[Path]:
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        raise SystemExit("can't read the video")
    edges = np.linspace(0, total, n + 1).astype(int)
    paths = []
    for i in range(n):
        best, best_sharp = None, -1.0
        for f in np.linspace(edges[i], max(edges[i], edges[i + 1] - 1), 5).astype(int):  # 5 tries per slice
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
            ok, img = cap.read()
            if not ok:
                continue
            sharp = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            if sharp > best_sharp:
                best, best_sharp = img, sharp
        if best is not None:
            h, w = best.shape[:2]
            s = 1024 / max(h, w)
            best = cv2.resize(best, (int(w * s), int(h * s))) if s < 1 else best
            p = out_dir / f"f{i:03d}.jpg"
            cv2.imwrite(str(p), best)
            paths.append(p)
    cap.release()
    if len(paths) < 4:
        raise SystemExit("not enough readable frames in the video")
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--frames", type=int, default=20, help="20 fits an 8 GB GPU")
    ap.add_argument("--keep", type=float, default=0.5, help="fraction of most-confident points to keep")
    args = ap.parse_args()

    from vggt.models.vggt import VGGT
    from vggt.utils.geometry import unproject_depth_map_to_point_map
    from vggt.utils.load_fn import load_and_preprocess_images
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if dev == "cuda" and torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    with tempfile.TemporaryDirectory() as tmp:
        frames = pick_frames(args.video, args.frames, Path(tmp))
        print(f"frames: {len(frames)} on {dev}", flush=True)
        model = VGGT.from_pretrained("facebook/VGGT-1B").to(dev).eval()
        images = load_and_preprocess_images([str(p) for p in frames]).to(dev)
        with torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=dtype, enabled=dev == "cuda"):
                pred = model(images)
        extr, intr = pose_encoding_to_extri_intri(pred["pose_enc"], images.shape[-2:])
        depth = pred["depth"].squeeze(0).float().cpu().numpy()          # [S, H, W, 1]
        conf = pred["depth_conf"].squeeze(0).float().cpu().numpy()      # [S, H, W]
        extr = extr.squeeze(0).float().cpu().numpy()                    # [S, 3, 4] camera-from-world
        intr = intr.squeeze(0).float().cpu().numpy()
        pts = unproject_depth_map_to_point_map(depth, extr, intr)       # [S, H, W, 3]
        cols = (images.permute(0, 2, 3, 1).float().cpu().numpy() * 255).astype(np.uint8)

    keep = conf >= np.quantile(conf, 1 - args.keep)
    points, colors = pts[keep], cols[keep]
    R, t = extr[:, :, :3], extr[:, :, 3]
    centers = -np.einsum("sji,sj->si", R, t)                            # C = -R^T t
    ups = np.einsum("sji,j->si", R, np.array([0.0, -1.0, 0.0]))         # camera "up" (OpenCV y is down)
    cam_up = ups.mean(0)
    np.savez_compressed(args.out, points=points.astype(np.float32), colors=colors,
                        cam_centers=centers.astype(np.float32), cam_up=(cam_up / np.linalg.norm(cam_up)).astype(np.float32))
    print(f"saved {len(points)} points from {len(frames)} frames -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
