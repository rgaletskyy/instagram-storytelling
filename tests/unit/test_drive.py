"""Talking to Drive: the token, and the folder a screenshot set lands in."""

import time

import pytest

from instagram_marketing_agent import drive

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Replays canned answers and records what was asked."""

    def __init__(self, gets=None, posts=None):
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.gets.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.posts.pop(0)


@pytest.fixture(autouse=True)
def _no_cached_token(monkeypatch):
    """The token cache is module state; a test must not inherit another's."""
    monkeypatch.setattr(drive, "_token", None)
    monkeypatch.setattr(drive, "load_dotenv", lambda: None)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "1//refresh")


def _token_response(expires_in=3600):
    return _Response(200, {"access_token": "ya29.token", "expires_in": expires_in})


async def test_one_token_serves_a_whole_run():
    """Exchanging the refresh token per upload would be a round trip each time."""
    client = _Client(posts=[_token_response()])

    first = await drive.access_token(client)
    second = await drive.access_token(client)

    assert first == second == "ya29.token"
    assert len(client.calls) == 1


async def test_a_stale_token_is_exchanged_again():
    client = _Client(posts=[_token_response(expires_in=0), _token_response()])

    await drive.access_token(client)
    # The cache keeps a minute of slack, so expires_in=0 is already past.
    await drive.access_token(client)

    assert len(client.calls) == 2


async def test_a_refused_refresh_token_says_what_google_said():
    client = _Client(posts=[_Response(400, text='{"error": "invalid_grant"}')])

    with pytest.raises(RuntimeError, match="invalid_grant"):
        await drive.access_token(client)


@pytest.mark.parametrize(
    "missing", ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_REFRESH_TOKEN"]
)
async def test_a_missing_credential_names_the_setting(monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    client = _Client(posts=[_token_response()])

    with pytest.raises(RuntimeError, match=missing):
        await drive.access_token(client)


async def test_an_existing_folder_is_reused(monkeypatch):
    """Or every run over the same clip would leave another folder behind."""
    monkeypatch.setattr(drive, "_token", ("ya29.token", time.time() + 600))
    client = _Client(gets=[_Response(200, {"files": [{"id": "already-there"}]})])

    folder, link = await drive.public_folder(client, "IMG_1", "parent-id")

    assert folder == "already-there"
    assert link == drive.folder_link("already-there")
    # Found, so nothing was created.
    assert [method for method, *_ in client.calls] == ["GET"]


async def test_a_new_folder_is_created_inside_the_parent(monkeypatch):
    monkeypatch.setattr(drive, "_token", ("ya29.token", time.time() + 600))
    client = _Client(
        gets=[_Response(200, {"files": []})],
        posts=[_Response(200, {"id": "new-folder"}), _Response(200, {})],
    )

    folder, link = await drive.public_folder(client, "IMG_1", "parent-id")

    assert folder == "new-folder"
    assert link == drive.folder_link("new-folder")
    create = next(call for call in client.calls if call[0] == "POST")
    assert create[2]["json"]["parents"] == ["parent-id"]
    assert create[2]["params"]["supportsAllDrives"] == "true"


async def test_a_folder_that_cannot_be_link_shared_is_still_usable(monkeypatch, caplog):
    """Workspace orgs commonly forbid it; the row must not be lost over that."""
    monkeypatch.setattr(drive, "_token", ("ya29.token", time.time() + 600))
    client = _Client(
        gets=[_Response(200, {"files": []})],
        posts=[
            _Response(200, {"id": "new-folder"}),
            _Response(403, text='{"error": "sharingRateLimitExceeded"}'),
        ],
    )

    folder, link = await drive.public_folder(client, "IMG_1", "parent-id")

    assert folder == "new-folder"
    assert link == drive.folder_link("new-folder")
    assert "could not be shared" in caplog.text


async def test_where_a_file_lives_is_read_from_drive(monkeypatch):
    monkeypatch.setattr(drive, "_token", ("ya29.token", time.time() + 600))
    client = _Client(gets=[_Response(200, {"parents": ["the-folder"]})])

    assert await drive.parent_of(client, "https://drive.google.com/file/d/abc/view") == (
        "the-folder"
    )


async def test_a_file_with_no_parent_says_there_is_nowhere_to_put_them(monkeypatch):
    monkeypatch.setattr(drive, "_token", ("ya29.token", time.time() + 600))
    client = _Client(gets=[_Response(200, {"parents": []})])

    with pytest.raises(RuntimeError, match="nowhere beside it"):
        await drive.parent_of(client, "abc")


async def test_a_web_page_instead_of_a_file_is_not_saved_as_one():
    """Drive answers an unshared file with HTML, which would be a corrupt image."""
    client = _Client(gets=[_Response(200, headers={"content-type": "text/html"})])

    with pytest.raises(RuntimeError, match="not shared publicly"):
        await drive.download(client, "https://drive.google.com/file/d/abc/view")
