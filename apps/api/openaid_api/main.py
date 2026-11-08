"""OpenAid API application factory."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from openaid_core.config import get_settings
from openaid_core.db import get_db
from .routers import datasets, facilities, geography, indicators, organisations


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OpenAid API",
        description=(
            "Open data. Stronger communities. Better decisions. — public REST API "
            "for OpenAid, the Africa-wide community resource & humanitarian "
            "intelligence platform. Figures without provenance are never served: "
            "every observation carries source, licence, period and value type."
        ),
        version="0.2.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    def health(session: Session = Depends(get_db)) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    app.include_router(geography.router)
    app.include_router(indicators.router)
    app.include_router(facilities.router)
    app.include_router(organisations.router)
    app.include_router(datasets.router)
    return app


app = create_app()
