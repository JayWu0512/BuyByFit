"""Application entry point.

Framework choice (FastAPI) and the error-response shape here are proposed by
B to unblock the recommendation endpoint -- needs Diwas/Isaac sign-off per
backend/WORKFLOW.md before this is the team's settled approach. Product and
room routes belong in their own app/api/v1/ modules, following the pattern
in searches.py, and get included below the same way.

Run with: uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.rooms import router as rooms_router
from app.api.v1.searches import router as searches_router


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

    app.include_router(searches_router)
    app.include_router(rooms_router)
    return app


app = create_application()
