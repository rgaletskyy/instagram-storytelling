"""POST /searchcontext: the user check, the response shape, the error mapping."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import MalformedError, TransportError

from api import app as api_app
from api import auth
from domain.contracts import (
    DataSourceError,
    EmbeddingError,
    InvalidArgument,
    Product,
    SearchResult,
)

pytestmark = pytest.mark.unit

ALLOWED = "anna@healthydoggo.ua"
TOKENS = {
    "good": {"email": "Anna@HealthyDoggo.ua", "email_verified": True},
    "stranger": {"email": "eve@example.com", "email_verified": True},
    "unverified": {"email": ALLOWED, "email_verified": False},
}


class _Search:
    def __init__(self, result=None, error=None):
        self.result = result or SearchResult()
        self.error = error
        self.queries = []

    async def find_similar(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(auth.AUDIENCE_ENV, "portal-client-id")
    monkeypatch.setenv(auth.ALLOWED_USERS_ENV, f" {ALLOWED.upper()} , other@healthydoggo.ua")
    seen = []

    def verify(token, audiences):
        seen.append(audiences)
        if token == "malformed":
            raise MalformedError("Can't parse segment")
        if token == "offline":
            raise TransportError("certificates unreachable")
        if token not in TOKENS:
            raise ValueError("Token used too late")
        return TOKENS[token]

    monkeypatch.setattr(auth, "verify_google_id_token", verify)
    return seen


def _client(search):
    return TestClient(api_app.create_app(search_service=search))


def _post(client, token="good", body=None):
    headers = {auth.USER_TOKEN_HEADER: token} if token else {}
    return client.post("/searchcontext", json=body or {"query": "шампунь"}, headers=headers)


def test_an_allowed_user_gets_the_search_result_in_contract_field_names(configured):
    search = _Search(SearchResult(products=[Product(sku="ND-1", price=295.0, distance=0.12)]))
    with _client(search) as client:
        response = _post(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"products", "instagramMessages", "content"}
    assert body["products"][0]["sku"] == "ND-1"
    assert body["products"][0]["distance"] == 0.12
    assert search.queries == ["шампунь"]
    assert configured == [("portal-client-id",)]


@pytest.mark.parametrize(
    ("token", "code"),
    [
        (None, 401),
        ("forged", 401),
        ("malformed", 401),
        ("unverified", 401),
        ("stranger", 403),
        ("offline", 503),
    ],
)
def test_unverified_or_unlisted_users_are_refused_before_searching(configured, token, code):
    search = _Search()
    with _client(search) as client:
        response = _post(client, token=token)
    assert response.status_code == code
    assert search.queries == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (InvalidArgument("query must not be empty"), 400),
        (EmbeddingError("jev down"), 502),
        (DataSourceError("firestore down"), 503),
    ],
)
def test_service_errors_map_to_status_codes(configured, error, code):
    with _client(_Search(error=error)) as client:
        assert _post(client).status_code == code


def test_a_body_without_query_is_rejected(configured):
    with _client(_Search()) as client:
        response = client.post("/searchcontext", json={}, headers={auth.USER_TOKEN_HEADER: "good"})
    assert response.status_code == 422


def test_each_call_is_logged_with_the_user(configured, capsys):
    with _client(_Search()) as client:
        _post(client)
        _post(client, token="stranger")

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    searched = next(line for line in lines if line["message"] == "searched")
    refused = next(line for line in lines if line["message"] == "refused")
    assert searched["user"] == ALLOWED and searched["status"] == 200
    assert refused["user"] == "eve@example.com" and refused["status"] == 403


@pytest.mark.parametrize("missing", [auth.AUDIENCE_ENV, auth.ALLOWED_USERS_ENV])
def test_the_app_refuses_to_start_without_auth_settings(configured, monkeypatch, missing):
    monkeypatch.setenv(missing, "")
    with pytest.raises(RuntimeError, match=missing):
        api_app.create_app(search_service=_Search())


@pytest.fixture(autouse=True)
def _fresh_logger():
    """Each app attaches its stdout handler once; let every test see its own."""
    logger = logging.getLogger("api")
    handlers = list(logger.handlers)
    logger.handlers.clear()
    yield
    logger.handlers[:] = handlers
