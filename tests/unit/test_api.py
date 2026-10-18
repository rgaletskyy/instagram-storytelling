"""POST /searchcontent: the user check, the response shape, the error mapping."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import MalformedError, TransportError

from api import app as api_app
from api import auth
from domain.content_insights_contracts import ContentInsights
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
    "mcp-service": {"email": "hd-mcp@project.iam.gserviceaccount.com", "email_verified": True},
    "portal-service": {
        "email": "hd-portal@project.iam.gserviceaccount.com",
        "email_verified": True,
    },
}
MCP_SA = "hd-mcp@project.iam.gserviceaccount.com"
API_URL = "https://hd-api.example.run.app"


class _Search:
    def __init__(self, result=None, error=None):
        self.result = result or SearchResult()
        self.error = error
        self.queries = []
        self.calls = []

    async def find_similar(self, query, has_dog=None, content_type="лайфстайл", product_sku=None):
        self.queries.append(query)
        self.calls.append(
            {"has_dog": has_dog, "content_type": content_type, "product_sku": product_sku}
        )
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


class _Insights:
    def __init__(self, result=None, error=None):
        self.result = result or ContentInsights()
        self.error = error
        self.calls = []

    async def query_content_insights(self, from_, **kwargs):
        self.calls.append({"from": from_, **kwargs})
        if self.error:
            raise self.error
        return self.result


def _client(search, insights=None):
    return TestClient(
        api_app.create_app(search_service=search, insights_service=insights or _Insights())
    )


def _post(client, token="good", body=None):
    headers = {auth.USER_TOKEN_HEADER: token} if token else {}
    return client.post("/searchcontent", json=body or {"query": "шампунь"}, headers=headers)


def test_an_allowed_user_gets_the_search_result_in_contract_field_names(configured):
    search = _Search(SearchResult(products=[Product(sku="ND-1", price=295.0, distance=0.12)]))
    with _client(search) as client:
        response = _post(client)

    assert response.status_code == 200
    body = response.json()
    # Empty properties are left out: no messages, no content, no product name.
    assert set(body) == {"products"}
    assert body["products"][0] == {"sku": "ND-1", "price": 295.0, "distance": 0.12}
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
        response = client.post("/searchcontent", json={}, headers={auth.USER_TOKEN_HEADER: "good"})
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


def test_has_dog_and_type_reach_the_service(configured):
    search = _Search()
    with _client(search) as client:
        response = _post(client, body={"query": "шпіц", "hasDog": True, "type": "креатив"})
    assert response.status_code == 200
    assert search.calls == [{"has_dog": True, "content_type": "креатив", "product_sku": None}]


def test_has_dog_and_type_default_to_any_dog_and_lifestyle(configured):
    search = _Search()
    with _client(search) as client:
        _post(client, body={"query": "шпіц"})
    assert search.calls == [{"has_dog": None, "content_type": "лайфстайл", "product_sku": None}]


def test_a_non_boolean_has_dog_is_rejected(configured):
    with _client(_Search()) as client:
        response = _post(client, body={"query": "шпіц", "hasDog": "maybe"})
    assert response.status_code == 422


def test_product_sku_reaches_the_service(configured):
    search = _Search()
    with _client(search) as client:
        response = _post(client, body={"query": "бальзам", "productSku": "ND-PAWS-01"})
    assert response.status_code == 200
    assert search.calls[0]["product_sku"] == "ND-PAWS-01"


@pytest.fixture
def service_callers(configured, monkeypatch):
    monkeypatch.setenv(auth.SERVICE_CALLERS_ENV, MCP_SA.upper())
    monkeypatch.setenv(auth.SERVICE_AUDIENCE_ENV, API_URL)
    return configured


def _post_as_service(client, bearer, body=None):
    return client.post(
        "/searchcontent",
        json=body or {"query": "бальзам"},
        headers={"Authorization": f"Bearer {bearer}"},
    )


def test_an_allowlisted_service_account_may_search_without_a_user(service_callers, capsys):
    search = _Search()
    with _client(search) as client:
        response = _post_as_service(client, "mcp-service")
    assert response.status_code == 200
    assert search.queries == ["бальзам"]
    # Checked against this API's own URL, not the portal's OAuth client.
    assert service_callers[-1] == (API_URL,)
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    searched = next(line for line in logged if line["message"] == "searched")
    assert searched["user"] == MCP_SA and searched["caller"] == "service"


@pytest.mark.parametrize(
    ("bearer", "code"), [("portal-service", 403), ("forged", 401), ("offline", 503)]
)
def test_other_service_tokens_are_refused(service_callers, bearer, code):
    search = _Search()
    with _client(search) as client:
        response = _post_as_service(client, bearer)
    assert response.status_code == code
    assert search.queries == []


def test_without_service_callers_configured_a_user_token_is_required(configured):
    search = _Search()
    with _client(search) as client:
        response = _post_as_service(client, "mcp-service")
    assert response.status_code == 401
    assert search.queries == []


def test_a_user_token_takes_precedence_over_the_service_token(service_callers):
    search = _Search()
    with _client(search) as client:
        response = client.post(
            "/searchcontent",
            json={"query": "q"},
            headers={auth.USER_TOKEN_HEADER: "stranger", "Authorization": "Bearer mcp-service"},
        )
    assert response.status_code == 403
    assert search.queries == []


@pytest.mark.parametrize("only", [auth.SERVICE_CALLERS_ENV, auth.SERVICE_AUDIENCE_ENV])
def test_half_a_service_configuration_refuses_to_start(configured, monkeypatch, only):
    monkeypatch.setenv(only, "x")
    with pytest.raises(RuntimeError, match="or neither"):
        api_app.create_app(search_service=_Search())


# --- POST /searchContentInsights -------------------------------------------------


def _insights(client, body, token="good"):
    return client.post("/searchContentInsights", json=body, headers={auth.USER_TOKEN_HEADER: token})


def test_content_insights_pass_the_filters_and_answer_in_contract_names(configured):
    insights = _Insights(ContentInsights(error_code="accessDenied", error_message="no"))
    body = {
        "from": "2026-10-01T00:00:00Z",
        "mediaProductType": "REELS",
        "sortBy": "views",
        "topN": 5,
    }
    with _client(_Search(), insights) as client:
        response = _insights(client, body)

    assert response.status_code == 200
    assert response.json() == {"errorCode": "accessDenied", "errorMessage": "no"}
    (call,) = insights.calls
    assert call["from"].isoformat() == "2026-10-01T00:00:00+00:00"
    assert (call["media_product_type"], call["sort_by"], call["to"]) == ("REELS", "views", None)
    assert call["top_n"] == 5


def test_content_insights_need_from_and_an_allowed_user(configured):
    insights = _Insights(error=InvalidArgument("sortBy must be one of ..."))
    with _client(_Search(), insights) as client:
        assert _insights(client, {}).status_code == 422
        assert _insights(client, {"from": "2026-10-01", "topN": "five"}).status_code == 422
        assert _insights(client, {"from": "2026-10-01"}, token="stranger").status_code == 403
        assert _insights(client, {"from": "2026-10-01", "sortBy": "x"}).status_code == 400
