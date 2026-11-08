"""Minimal Vertex AI (Gemini) client.

Auth: Google Application Default Credentials (`gcloud auth application-default login` locally, or a
service account on a server). Project: GOOGLE_CLOUD_PROJECT / VERTEX_PROJECT, else the credentials'
quota project.

429/503: Gemini on Vertex uses Dynamic Shared Quota, so a 429 means the model's shared pool is busy for a
moment, not that our project ran out. Short exponential backoff with jitter (~2, 4, 8 s) gets through fastest;
the old fixed 15/30/45 s waits turned a busy second into a 60-100 s render. After the retries, RateLimited is
raised so the caller can switch to a model on another pool (see pipeline.render).

    text = generate(MODEL, [image_bytes, "prompt"])
    data = generate_json(MODEL, [image_bytes, "prompt"], schema=PydanticModel)
    png  = generate(IMAGE_MODEL, [photo, "prompt"], image_out=True, aspect="3:4")
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)
_creds = None
_lock = threading.Lock()

BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 4.0


class RateLimited(RuntimeError):
    """The model kept answering 429/503 through every retry."""


def backoff(attempt: int) -> float:
    """A random 2-4 s wait (jitter so parallel callers don't retry in lockstep)."""
    return random.uniform(BACKOFF_BASE_S, BACKOFF_MAX_S)


def _token_and_project() -> tuple[str, str]:
    global _creds
    import google.auth
    import google.auth.transport.requests

    with _lock:
        if _creds is None:
            _creds = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds, project = _creds
        if not creds.valid:
            creds.refresh(google.auth.transport.requests.Request())
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT") or project
               or getattr(creds, "quota_project_id", None))
    if not project:
        raise RuntimeError("No Google Cloud project: set GOOGLE_CLOUD_PROJECT")
    return creds.token, project


def _mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def _inline_refs(schema: dict) -> dict:
    """Pydantic nests models under $defs/$ref; inline them for Gemini's schema support."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def generate(model: str, parts: list, *, json_schema: dict | None = None, image_out: bool = False,
             aspect: str | None = None, thinking: str | None = None, retries: int = 4, timeout: int = 180):
    """parts: bytes (images) and str (text), in order. Returns text, or image bytes if image_out."""
    body_parts = [{"inlineData": {"mimeType": _mime(p), "data": base64.b64encode(p).decode()}} if isinstance(p, bytes)
                  else {"text": p} for p in parts]
    config: dict = {}
    if image_out:
        config["responseModalities"] = ["IMAGE"]
        if aspect:
            config["imageConfig"] = {"aspectRatio": aspect}
    if json_schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = json_schema
    if thinking:
        config["thinkingConfig"] = {"thinkingLevel": thinking}
    body = json.dumps({"contents": [{"role": "user", "parts": body_parts}], "generationConfig": config}).encode()

    for attempt in range(retries + 1):
        token, project = _token_and_project()
        req = urllib.request.Request(
            f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent",
            data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                "x-goog-user-project": project})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                out = json.loads(res.read())
            break
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            if e.code == 400 and thinking and "thinking" in detail.lower():
                return generate(model, parts, json_schema=json_schema, image_out=image_out, aspect=aspect,
                                thinking=None, retries=retries, timeout=timeout)
            if e.code in (429, 503) and attempt < retries:
                wait = backoff(attempt)
                log.warning("%s %s, retrying in %.1fs", model, e.code, wait)
                time.sleep(wait)
                continue
            if e.code in (429, 503):
                raise RateLimited(f"{model} {e.code} after {retries} retries: {detail}") from None
            raise RuntimeError(f"{model} {e.code}: {detail}") from None

    cand = (out.get("candidates") or [{}])[0]
    parts_out = cand.get("content", {}).get("parts", [])
    if image_out:
        for p in parts_out:
            data = (p.get("inlineData") or {}).get("data")
            if data:
                return base64.b64decode(data)
        raise RuntimeError(f"{model} returned no image (finishReason={cand.get('finishReason')})")
    text = "".join(p.get("text", "") for p in parts_out if not p.get("thought"))
    if not text:
        raise RuntimeError(f"{model} returned no text (finishReason={cand.get('finishReason')})")
    return text


def generate_json(model: str, parts: list, schema, **kw) -> dict:
    """Structured output: Gemini is constrained to `schema` (a Pydantic model) and the answer is validated
    with Pydantic. Retries once on invalid JSON. Returns a plain dict."""
    from pydantic import ValidationError

    for attempt in (1, 2):
        text = generate(model, parts, json_schema=_inline_refs(schema.model_json_schema()), **kw)
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return schema.model_validate_json(text).model_dump()
        except ValidationError as error:
            if attempt == 2:
                raise RuntimeError(f"{model} gave invalid JSON twice: {str(error)[:200]}") from None
    raise AssertionError("unreachable")
