"""Background visualization jobs (a run takes ~40-110 s: too long for one HTTP request).

One job runs at a time (Vertex per-minute quota); later ones wait as "queued".
In memory: a restart forgets running jobs (finished results stay in storage as summary_<job>.json).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import pipeline

log = logging.getLogger(__name__)
_jobs: dict[str, dict] = {}
_runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="visualize")
_lock = threading.Lock()


def start(room_id: str, brief: str, products: list[dict]) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "room_id": room_id, "status": "queued", "stage": "queued", "info": {}, "_t": time.time()}
    with _lock:
        _jobs[job_id] = job

    def on_stage(stage, info=None):
        job["stage"] = stage
        if info:
            job["info"] = {**job["info"], **info}

    def work():
        job["status"] = "running"
        try:
            job["result"] = pipeline.run(room_id, job_id, brief, products, on_stage)
            job["status"] = "done"
        except Exception as error:  # the page shows the reason
            log.exception("visualization %s failed", job_id)
            job["status"], job["error"] = "error", str(error)[:300]
        job["elapsed_s"] = round(time.time() - job["_t"], 1)

    _runner.submit(work)
    return job_id


def get(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out.setdefault("elapsed_s", round(time.time() - job["_t"], 1))
    return out
