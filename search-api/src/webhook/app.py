"""Meta's webhook for story insights. Run it with

    uv run uvicorn webhook.app:create_app --factory --port 8080

A story and its insights last 24 hours, so instead of being polled they are
pushed: Meta POSTs a `story_insights` notification when a story expires, and
this app merges it into BigQuery's `organic` table as a STORY row. It is
public (Meta cannot carry a Google token), deployed apart from the private
search API, and accepts only what Meta signed with the app secret
(specs/meta/webhooks.md).

- GET  /meta/webhook  answers Meta's verification with `hub.challenge`.
- POST /meta/webhook  takes notifications. Meta retries for up to 36 hours
  until it gets a 2xx, so a failure to store answers 500; merging by id makes
  a retried notification harmless.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from api.app import _configure_logging
from infrastructure.bigquery_client import BigQueryClient, BigQueryError
from infrastructure.instagram_meta_client import InstagramMedia, InstagramMetaClient, MetaApiError
from routines.insights_sync.rows import organic_row

logger = logging.getLogger("api")

APP_SECRET_ENV = "META_APP_SECRET"
VERIFY_TOKEN_ENV = "META_WEBHOOK_VERIFY_TOKEN"
SIGNATURE_HEADER = "X-Hub-Signature-256"
STORY_INSIGHTS = "story_insights"
# Older payloads split navigation into these instead of sending its total.
_NAVIGATION_PARTS = ("taps_forward", "taps_back", "exits", "swipe_forward")


def create_app(
    bigquery: BigQueryClient | None = None, meta: InstagramMetaClient | None = None
) -> FastAPI:
    from infrastructure.env import load_dotenv

    load_dotenv()
    _configure_logging()
    app_secret = os.environ.get(APP_SECRET_ENV, "")
    verify_token = os.environ.get(VERIFY_TOKEN_ENV, "")
    # Fail closed: without the secret, anyone could write rows.
    missing = [
        n for n, v in ((APP_SECRET_ENV, app_secret), (VERIFY_TOKEN_ENV, verify_token)) if not v
    ]
    if missing:
        raise RuntimeError(f"not set: {', '.join(missing)}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.bigquery = bigquery or BigQueryClient()
        app.state.meta = meta or InstagramMetaClient()
        yield

    app = FastAPI(title="HealthyDoggo Meta webhook", lifespan=lifespan)

    @app.get("/meta/webhook", response_class=PlainTextResponse)
    async def verify(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        if mode != "subscribe" or not hmac.compare_digest(token, verify_token):
            logger.warning("webhook verification refused")
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        return challenge

    @app.post("/meta/webhook")
    async def notify(request: Request) -> dict:
        body = await request.body()
        if not _signed(body, request.headers.get(SIGNATURE_HEADER, ""), app_secret):
            logger.warning("webhook notification with a bad signature refused")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED)
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "not JSON") from exc

        rows = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != STORY_INSIGHTS:
                    continue
                value = change.get("value") or {}
                if not value.get("media_id"):
                    continue
                story = await _story(app.state.meta, value["media_id"], entry.get("time"))
                rows.append(organic_row(story, _metrics(value)))
        try:
            stored = await app.state.bigquery.merge_organic(rows)
        except BigQueryError as exc:
            logger.error("story insights not stored: %s", exc)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
        logger.info("story insights stored", extra={"fields": {"stories": stored}})
        return {"stored": stored}

    return app


def _signed(body: bytes, header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header)


async def _story(meta: InstagramMetaClient, media_id: str, sent: int | None) -> InstagramMedia:
    """The story's own fields from the Graph API; the bare minimum if it will not say."""
    try:
        story = await meta.media(media_id)
    except MetaApiError as exc:
        logger.warning("story %s not found in the Graph API: %s", media_id, exc)
        # When it was published is unknown; when Meta sent this is the
        # closest there is.
        moment = datetime.fromtimestamp(sent, UTC) if sent else datetime.now(UTC)
        return InstagramMedia(media_id, "", "STORY", moment)
    return InstagramMedia(
        story.id,
        story.media_type,
        "STORY",
        story.timestamp,
        story.permalink,
        story.caption,
        story.media_url,
        story.thumbnail_url,
    )


def _metrics(value: dict) -> dict[str, float]:
    """The notification's numbers by Graph API metric name."""
    metrics = {
        k: v for k, v in value.items() if isinstance(v, int | float) and not isinstance(v, bool)
    }
    if "navigation" not in metrics and any(k in metrics for k in _NAVIGATION_PARTS):
        metrics["navigation"] = sum(metrics.get(k, 0) for k in _NAVIGATION_PARTS)
    return metrics
