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
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from domain.content_insights_contracts import ContentInsights
from domain.content_insights_service import ContentInsightsService
from domain.content_search_service import DEFAULT_CONTENT_TYPE, SearchService
from domain.contracts import DataSourceError, EmbeddingError, InvalidArgument, SearchResult

from .auth import AuthSettings, User, current_user
from .responses import without_empty

logger = logging.getLogger("api")


class SearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str
    # Narrow content results: with or without a dog (any, when absent), and of
    # one type. Ignored by products and messages.
    has_dog: bool | None = Field(default=None, alias="hasDog")
    content_type: str = Field(default=DEFAULT_CONTENT_TYPE, alias="type")
    # Narrow products to this one SKU. Ignored by content and messages.
    product_sku: str | None = Field(default=None, alias="productSku")


class InsightsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime | None = None
    media_type: str | None = Field(default=None, alias="mediaType")
    media_product_type: str | None = Field(default=None, alias="mediaProductType")
    sort_by: str | None = Field(default=None, alias="sortBy")
    top_n: int | None = Field(default=None, alias="topN")


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


def create_app(
    search_service: SearchService | None = None,
    insights_service: ContentInsightsService | None = None,
) -> FastAPI:
    from infrastructure.env import load_dotenv

    load_dotenv()
    _configure_logging()
    auth = AuthSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Built once and shared: the clients hold connections worth reusing.
        app.state.search = search_service or SearchService()
        app.state.insights = insights_service or ContentInsightsService()
        yield

    app = FastAPI(title="HealthyDoggo API", lifespan=lifespan)
    app.state.auth = auth

    @app.post("/searchcontent", response_model=SearchResult, response_model_by_alias=True)
    @without_empty
    async def search_context(body: SearchRequest, user: Annotated[User, Depends(current_user)]):
        started = time.perf_counter()
        fields = {
            "user": user.email,
            "caller": "service" if user.is_service else "user",
            "action": "searchcontent",
            "hasDog": body.has_dog,
            "type": body.content_type,
            "productSku": body.product_sku,
            "query": body.query,
        }
        try:
            result = await app.state.search.find_similar(
                body.query,
                has_dog=body.has_dog,
                content_type=body.content_type,
                product_sku=body.product_sku,
            )
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

    @app.post(
        "/searchContentInsights", response_model=ContentInsights, response_model_by_alias=True
    )
    @without_empty
    async def content_insights(body: InsightsRequest, user: Annotated[User, Depends(current_user)]):
        started = time.perf_counter()
        fields = {
            "user": user.email,
            "caller": "service" if user.is_service else "user",
            "action": "searchContentInsights",
            "from": body.from_,
            "to": body.to,
            "mediaType": body.media_type,
            "mediaProductType": body.media_product_type,
            "sortBy": body.sort_by,
            "topN": body.top_n,
        }
        try:
            result = await app.state.insights.query_content_insights(
                body.from_,
                to=body.to,
                media_type=body.media_type,
                media_product_type=body.media_product_type,
                sort_by=body.sort_by,
                top_n=body.top_n,
            )
        except InvalidArgument as exc:
            _log(logging.INFO, "rejected", fields, started, status=400)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        # A BigQuery failure is part of the answer (errorCode), as the spec has it.
        level = logging.ERROR if result.error_code else logging.INFO
        message = f"bigquery failed: {result.error_message}" if result.error_code else "queried"
        _log(level, message, fields, started, status=200, items=len(result.items))
        return result

    return app


def _log(level: int, message: str, fields: dict, started: float, **extra) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000)
    logger.log(level, message, extra={"fields": {**fields, **extra, "durationMs": duration_ms}})
