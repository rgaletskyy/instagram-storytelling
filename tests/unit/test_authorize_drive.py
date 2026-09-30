"""Minting the Drive refresh token: the parts that can be got wrong silently."""

from urllib.parse import parse_qs, urlparse

import pytest

from instagram_marketing_agent import authorize_drive
from instagram_marketing_agent.authorize_drive import SCOPE, auth_url, exchange

pytestmark = pytest.mark.unit

REDIRECT = "http://127.0.0.1:54321/"


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_the_consent_url_asks_for_a_refresh_token():
    """Without offline access and a forced prompt, Google returns none."""
    query = _query(auth_url("client-id", REDIRECT, "state-123"))

    assert query["access_type"] == "offline"
    assert query["prompt"] == "consent"
    assert query["scope"] == SCOPE
    assert query["redirect_uri"] == REDIRECT
    assert query["response_type"] == "code"
    assert query["state"] == "state-123"


def test_the_scope_is_full_drive():
    """drive.file cannot see a video this app did not upload."""
    assert SCOPE == "https://www.googleapis.com/auth/drive"
    assert not SCOPE.endswith(".file")


def test_no_redirect_uri_means_any_free_port(monkeypatch):
    """What a Desktop client allows, and why nothing has to be registered."""
    server, uri = authorize_drive.bind(None)
    try:
        assert uri == f"http://127.0.0.1:{server.server_port}/"
        assert server.server_port != 0
    finally:
        server.server_close()


def test_a_registered_uri_is_used_verbatim():
    """A Web client compares the string, so path and host must survive intact."""
    server, uri = authorize_drive.bind("http://localhost:8765/callback")
    try:
        assert uri == "http://localhost:8765/callback"
        assert server.server_port == 8765
    finally:
        server.server_close()


def test_a_redirect_somewhere_other_than_loopback_is_refused():
    with pytest.raises(RuntimeError, match="not a loopback address"):
        authorize_drive.bind("https://example.com/callback")


def test_a_port_already_taken_says_so():
    held, _ = authorize_drive.bind("http://localhost:8766/callback")
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            authorize_drive.bind("http://localhost:8766/callback")
    finally:
        held.server_close()


class _Server:
    """Stands in for the loopback server, replaying one redirect."""

    timeout = 300

    def __init__(self, query):
        self._replies = [query]
        self.query = None

    def handle_request(self):
        self.query = self._replies.pop(0)


def test_a_code_is_read_off_the_redirect():
    server = _Server({"code": "one-time-code", "state": "abc"})
    assert authorize_drive.wait_for_code(server, "abc") == "one-time-code"


def test_a_redirect_from_somewhere_else_is_refused():
    """The state is the only thing tying the redirect to the page we opened."""
    server = _Server({"code": "planted", "state": "not-ours"})
    with pytest.raises(RuntimeError, match="wrong state"):
        authorize_drive.wait_for_code(server, "abc")


def test_a_refused_consent_says_so():
    server = _Server({"error": "access_denied", "state": "abc"})
    with pytest.raises(RuntimeError, match="access_denied"):
        authorize_drive.wait_for_code(server, "abc")


def test_a_silent_browser_times_out_rather_than_hanging():
    server = _Server(None)
    with pytest.raises(TimeoutError, match="no response from the browser"):
        authorize_drive.wait_for_code(server, "abc")


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_the_refresh_token_comes_back_from_the_exchange(monkeypatch):
    sent = {}

    def fake_post(url, data=None, timeout=None):
        sent.update(url=url, **data)
        return _Response(200, {"refresh_token": "1//real", "access_token": "ya29."})

    monkeypatch.setattr(authorize_drive.httpx, "post", fake_post)

    assert exchange("code", "id", "secret", REDIRECT) == "1//real"
    assert sent["grant_type"] == "authorization_code"
    assert sent["redirect_uri"] == REDIRECT


def test_an_access_token_without_a_refresh_token_is_an_error(monkeypatch):
    """The failure that otherwise looks like success until an hour later."""

    def fake_post(url, data=None, timeout=None):
        return _Response(200, {"access_token": "ya29."})

    monkeypatch.setattr(authorize_drive.httpx, "post", fake_post)

    with pytest.raises(RuntimeError, match="no refresh token"):
        exchange("code", "id", "secret", REDIRECT)


def test_a_rejected_code_carries_googles_reason(monkeypatch):
    def fake_post(url, data=None, timeout=None):
        return _Response(400, text='{"error": "invalid_grant"}')

    monkeypatch.setattr(authorize_drive.httpx, "post", fake_post)

    with pytest.raises(RuntimeError, match="invalid_grant"):
        exchange("code", "id", "secret", REDIRECT)


def test_a_missing_client_names_both_settings(monkeypatch):
    monkeypatch.setattr(authorize_drive, "load_dotenv", lambda: None)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_OAUTH_CLIENT_ID"):
        authorize_drive._client()
