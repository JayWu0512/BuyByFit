"""Application entry point.

Framework choice (FastAPI) and the error-response shape here are proposed by
B to unblock the recommendation endpoint -- needs Diwas/Isaac sign-off per
backend/WORKFLOW.md before this is the team's settled approach. Product and
room routes belong in their own app/api/v1/ modules, following the pattern
in searches.py, and get included below the same way.

Run with: uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.rooms import router as rooms_router
from app.api.v1.searches import router as searches_router

# Python's root logger defaults to WARNING, which silently drops every log.info() call across the
# codebase (e.g. pipeline.py's design-plan/room-context diagnostics) -- they run, but never reach Cloud
# Logging. Set once, here, since this is the actual process entrypoint (uvicorn app.main:app).
logging.basicConfig(level=logging.INFO)


def create_application() -> FastAPI:
    """Build and return the web application instance."""
    app = FastAPI(title="BuyByFit API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": exc.detail, "status": exc.status_code}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        # API_CONTRACT.md rule 3 requires {"error": {...}}; the mock also
        # returns 400 (not FastAPI's default 422) for bad input, so this
        # keeps both error shape and status code compatible with it.
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "invalid request", "status": 400}},
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "live"}

    @app.on_event("startup")
    def _warm_embedding_model() -> None:
        # fastembed downloads its model (~67MB) lazily on first use. Doing that for the first time
        # inside a visualization job is risky: app/services/three_d/jobs.py runs one job at a time, so a
        # slow/cold download there can stall every other visualization behind it. Starting the download
        # here, in a background thread, gives it a head start before real traffic arrives. Best-effort:
        # if it fails, the first real request just pays the cost itself (recommend.py/pipeline.py both
        # already handle that case).
        def warm() -> None:
            try:
                from app.services.logic.embeddings import embed_query

                embed_query("warm up")
            except Exception:
                pass

        threading.Thread(target=warm, daemon=True).start()

    app.include_router(searches_router)
    app.include_router(rooms_router)
    return app


app = create_application()
