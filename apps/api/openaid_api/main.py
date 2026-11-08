"""OpenAid API application factory."""

from __future__ import annotations

import threading
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from openaid_core.config import get_settings
from openaid_core.db import get_db
from .routers import auth, datasets, facilities, geography, governance, indicators, organisations


class RateLimitMiddleware:
    """Per-IP fixed-window limiter for /api/* routes.

    In-memory and single-process by design for Phase 2 — documented as not
    production-cluster-grade (swap for a Redis-backed limiter when the
    platform scales horizontally). Disabled when the limit is 0.
    """

    def __init__(self, app: object, limit_per_minute: int) -> None:
        self.app = app
        self.limit = limit_per_minute
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _client(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def __call__(self, scope, receive, send):  # ASGI contract
        if scope["type"] != "http" or self.limit <= 0 or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        key = self._client(Request(scope, receive))
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            hits = [t for t in self._events.get(key, []) if t > window_start]
            if len(hits) >= self.limit:
                self._events[key] = hits
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded; retry shortly"},
                    headers={"Retry-After": "60"},
                )
                await response(scope, receive, send)
                return
            hits.append(now)
            self._events[key] = hits
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OpenAid API",
        description=(
            "Open data. Stronger communities. Better decisions. — public REST API "
            "for OpenAid, the Africa-wide community resource & humanitarian "
            "intelligence platform. Figures without provenance are never served: "
            "every observation carries source, licence, period and value type. "
            "Write endpoints require an authenticated reviewer/admin token; "
            "corrections flow through the submissions-and-review workflow."
        ),
        version="0.3.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.rate_limit_per_minute > 0:
        app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)

    @app.get("/health", tags=["system"])
    def health(session: Session = Depends(get_db)) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    app.include_router(auth.router)
    app.include_router(geography.router)
    app.include_router(indicators.router)
    app.include_router(facilities.router)
    app.include_router(organisations.router)
    app.include_router(datasets.router)
    app.include_router(governance.router)
    return app


app = create_app()
