"""The FastAPI app. Run it with

    uv run uvicorn api.app:create_app --factory --port 8080

Built by a factory so that configuration is read when the server starts, not
when the module is imported: a missing setting stops the server at once
rather than failing every request.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from domain.contracts import DataSourceError, EmbeddingError, InvalidArgument, SearchResult
from domain.search_service import SearchService

from .auth import AuthSettings, User, current_user

logger = logging.getLogger("api")


class SearchRequest(BaseModel):
    query: str


class _CloudLoggingFormatter(logging.Formatter):
    """One JSON object per line, which Cloud Logging parses into fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage()}
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, ensure_ascii=False, default=str)


def _configure_logging() -> None:
    if any(isinstance(h.formatter, _CloudLoggingFormatter) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_CloudLoggingFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app(search_service: SearchService | None = None) -> FastAPI:
    from instagram_marketing_agent.config import load_dotenv

    load_dotenv()
    _configure_logging()
    auth = AuthSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Built once and shared: the clients hold connections worth reusing.
        app.state.search = search_service or SearchService()
        yield

    app = FastAPI(title="HealthyDoggo API", lifespan=lifespan)
    app.state.auth = auth

    @app.post("/searchcontext", response_model=SearchResult, response_model_by_alias=True)
    async def search_context(body: SearchRequest, user: Annotated[User, Depends(current_user)]):
        started = time.perf_counter()
        fields = {"user": user.email, "action": "searchcontext"}
        try:
            result = await app.state.search.find_similar(body.query)
        except InvalidArgument as exc:
            _log(logging.INFO, "rejected", fields, started, status=400)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except EmbeddingError as exc:
            _log(
                logging.ERROR, f"embedding or classifier failed: {exc}", fields, started, status=502
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail="search is unavailable"
            ) from exc
        except DataSourceError as exc:
            _log(logging.ERROR, f"firestore failed: {exc}", fields, started, status=503)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail="search is unavailable"
            ) from exc
        _log(
            logging.INFO,
            "searched",
            fields,
            started,
            status=200,
            products=len(result.products),
            instagramMessages=len(result.instagram_messages),
            content=len(result.content),
        )
        return result

    return app


def _log(level: int, message: str, fields: dict, started: float, **extra) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000)
    logger.log(level, message, extra={"fields": {**fields, **extra, "durationMs": duration_ms}})
