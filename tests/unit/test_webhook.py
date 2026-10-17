"""Meta's story-insights webhook: verification, signatures, rows stored."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from infrastructure.bigquery_client import BigQueryError
from infrastructure.instagram_meta_client import InstagramMedia, MetaApiError
from webhook import app as webhook_app

pytestmark = pytest.mark.unit

SECRET = "app-secret"
STORY = InstagramMedia(
    "s1", "IMAGE", "STORY", datetime(2026, 10, 16, 8, tzinfo=UTC), "https://ig/s1"
)


class _BigQuery:
    def __init__(self, error=None):
        self.rows, self.error = [], error

    async def merge_organic(self, rows):
        if self.error:
            raise self.error
        self.rows.extend(rows)
        return len(rows)


class _Meta:
    def __init__(self, found=True):
        self.found = found

    async def media(self, media_id):
        if not self.found:
            raise MetaApiError("Unsupported get request", code=100)
        return STORY


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv(webhook_app.APP_SECRET_ENV, SECRET)
    monkeypatch.setenv(webhook_app.VERIFY_TOKEN_ENV, "verify-me")
    logger = logging.getLogger("api")
    handlers = list(logger.handlers)
    logger.handlers.clear()
    yield
    logger.handlers[:] = handlers


def _client(bigquery=None, meta=None):
    return TestClient(webhook_app.create_app(bigquery or _BigQuery(), meta or _Meta()))


def _notify(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/meta/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )


def _story_insights(value, time=1760688000):
    return {
        "object": "instagram",
        "entry": [{"id": "1784", "time": time, "changes": [{"field": "story_insights", "value": value}]}],
    }  # fmt: skip


def test_verification_echoes_the_challenge_only_for_the_right_token():
    with _client() as client:
        ok = client.get("/meta/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1158201444"})  # fmt: skip
        wrong = client.get("/meta/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"})  # fmt: skip

    assert (ok.status_code, ok.text) == (200, "1158201444")
    assert wrong.status_code == 403


def test_a_story_notification_is_stored_as_a_story_row():
    bigquery = _BigQuery()
    with _client(bigquery) as client:
        response = _notify(client, _story_insights(
            {"media_id": "s1", "reach": 44, "views": 60, "replies": 0, "taps_forward": 4, "taps_back": 3, "exits": 3}
        ))  # fmt: skip

    assert response.status_code == 200
    (row,) = bigquery.rows
    assert (row["id"], row["mediaProductType"], row["permaLink"]) == (
        "s1",
        "STORY",
        "https://ig/s1",
    )
    assert (row["reach"], row["views"], row["replies"], row["navigation"]) == (44, 60, 0, 10)
    assert row["timestamp"] == STORY.timestamp


def test_a_story_the_graph_api_no_longer_shows_is_stored_with_what_is_known():
    bigquery = _BigQuery()
    with _client(bigquery, _Meta(found=False)) as client:
        _notify(client, _story_insights({"media_id": "s2", "reach": 7}, time=1760688000))

    (row,) = bigquery.rows
    assert (row["id"], row["mediaType"], row["mediaProductType"]) == ("s2", "", "STORY")
    assert row["timestamp"] == datetime.fromtimestamp(1760688000, UTC)


@pytest.mark.parametrize("secret", ["not-the-secret", None])
def test_unsigned_or_wrongly_signed_notifications_are_refused(secret):
    bigquery = _BigQuery()
    with _client(bigquery) as client:
        if secret:
            response = _notify(client, _story_insights({"media_id": "s1"}), secret=secret)
        else:
            response = client.post("/meta/webhook", json=_story_insights({"media_id": "s1"}))

    assert response.status_code == 401
    assert bigquery.rows == []


def test_other_fields_are_acknowledged_and_ignored():
    bigquery = _BigQuery()
    payload = {
        "object": "instagram",
        "entry": [{"changes": [{"field": "comments", "value": {"id": "c"}}]}],
    }
    with _client(bigquery) as client:
        assert _notify(client, payload).status_code == 200
    assert bigquery.rows == []


def test_a_storage_failure_answers_500_so_meta_retries():
    with _client(_BigQuery(error=BigQueryError("backendError", "try again"))) as client:
        assert _notify(client, _story_insights({"media_id": "s1"})).status_code == 500


def test_the_app_refuses_to_start_without_the_app_secret(monkeypatch):
    monkeypatch.setenv(webhook_app.APP_SECRET_ENV, "")
    with pytest.raises(RuntimeError, match=webhook_app.APP_SECRET_ENV):
        webhook_app.create_app(_BigQuery(), _Meta())
