"""One-shot consent: turn the OAuth client in .env into a refresh token.

Run once, when Drive uploading is first set up and again if the token is ever
revoked. Everything after that uses the refresh token, which an Internal app's
tokens do not expire on their own.

Loopback rather than a pasted code: Google retired the copy-paste (`oob`) flow,
and a Desktop client accepts any 127.0.0.1 port without registering it.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import load_dotenv
from .drive import CLIENT_ID_ENV, CLIENT_SECRET_ENV, REFRESH_TOKEN_ENV, TOKEN_URL

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# A Desktop client accepts any loopback port, so nothing has to be registered.
# A Web client accepts only the exact URIs registered against it, and rejects
# anything else with "Access blocked: This app's request is invalid".
LOOPBACK_HOST = "127.0.0.1"
# Full drive, not drive.file: the screenshot folder is created beside a video
# this app did not upload, and drive.file cannot see it.
SCOPE = "https://www.googleapis.com/auth/drive"
# Long enough to find the right Google account and read the consent screen.
CONSENT_TIMEOUT = 300

_DONE_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>Authorised</title>
<body style="font:16px system-ui;padding:3rem">
<h1>Authorised</h1><p>Close this tab and go back to the terminal.</p>
"""


def auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Where the browser goes to ask for consent.

    `access_type=offline` with `prompt=consent` is what makes Google return a
    refresh token. Drop either and a second run yields an access token only,
    which looks like success until the first upload an hour later.
    """
    return f"{AUTH_URL}?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )


class _Catcher(BaseHTTPRequestHandler):
    """Catches the one redirect Google sends back."""

    def do_GET(self) -> None:  # noqa: N802 - the name is BaseHTTPRequestHandler's
        query = parse_qs(urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            # A favicon or a probe. Answer it without consuming the wait.
            self.send_response(404)
            self.end_headers()
            return
        self.server.query = {k: v[0] for k, v in query.items()}  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_DONE_PAGE)

    def log_message(self, *_args) -> None:
        """Quiet: the handler's own logging would talk over the instructions."""


def wait_for_code(server: HTTPServer, state: str) -> str:
    """Serve until the redirect arrives, and return the code it carries."""
    server.query = None  # type: ignore[attr-defined]
    while server.query is None:  # type: ignore[attr-defined]
        server.handle_request()
        if server.query is None:  # type: ignore[attr-defined]
            raise TimeoutError(
                f"no response from the browser within {server.timeout:g}s -- "
                f"run it again and finish the consent screen"
            )

    query: dict = server.query  # type: ignore[attr-defined]
    if query.get("error"):
        raise RuntimeError(f"consent was refused: {query['error']}")
    if query.get("state") != state:
        raise RuntimeError(
            "the redirect carried the wrong state, so it did not come from the "
            "page this command opened; run it again"
        )
    return query["code"]


def exchange(code: str, client_id: str, client_secret: str, redirect_uri: str) -> str:
    """Trade the one-time code for a refresh token."""
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Google refused the code ({response.status_code}): "
            f"{response.text.strip()[:300]}"
        )
    payload = response.json()
    token = payload.get("refresh_token")
    if not token:
        raise RuntimeError(
            "Google returned an access token but no refresh token. That happens "
            "when the client is a Web application rather than a Desktop app, or "
            "when this account has already consented -- revoke the app at "
            "https://myaccount.google.com/permissions and run this again."
        )
    return token


def bind(redirect_uri: str | None) -> tuple[HTTPServer, str]:
    """The server to catch the redirect on, and the URI to ask Google for.

    Without a URI the OS picks a port, which is what a Desktop client allows.
    With one, the port and path are taken from it verbatim -- a Web client
    compares the string it was given against the ones registered against it, so
    the two have to match exactly, `localhost` and trailing slash included.
    """
    if redirect_uri is None:
        server = HTTPServer((LOOPBACK_HOST, 0), _Catcher)
        return server, f"http://{LOOPBACK_HOST}:{server.server_port}/"

    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError(
            f"{redirect_uri} is not a loopback address; this command can only "
            f"catch a redirect sent back to localhost"
        )
    try:
        server = HTTPServer((LOOPBACK_HOST, parsed.port or 80), _Catcher)
    except OSError as exc:
        raise RuntimeError(
            f"port {parsed.port} is already in use, so the redirect cannot be "
            f"caught there: {exc}"
        ) from exc
    return server, redirect_uri


def _client() -> tuple[str, str]:
    """The OAuth client from .env, or a message naming what is missing."""
    load_dotenv()
    client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
    secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
    if not client_id or not secret:
        raise RuntimeError(
            f"{CLIENT_ID_ENV} and {CLIENT_SECRET_ENV} must be in .env before "
            f"this can run. Create a Desktop app client under Google Auth "
            f"Platform -> Clients and copy both values in."
        )
    return client_id, secret


def main() -> int:
    # Parsed before anything else: without it, any stray argument -- --help
    # included -- opens a browser and sits waiting for a consent nobody asked for.
    parser = argparse.ArgumentParser(
        prog="authorize-drive",
        description=(
            "One-shot consent: turn the OAuth client in .env into the refresh "
            "token that lets --index-images upload video screenshots to Drive."
        ),
    )
    parser.add_argument(
        "--redirect-uri",
        default=None,
        metavar="URI",
        help="the redirect URI registered against a Web-app client, e.g. "
        "http://localhost:8765/callback. Leave it out for a Desktop client, "
        "which accepts any loopback port without registering one",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=CONSENT_TIMEOUT,
        metavar="SECONDS",
        help=f"how long to wait for the consent screen (default {CONSENT_TIMEOUT})",
    )
    args = parser.parse_args()

    try:
        client_id, secret = _client()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        server, redirect_uri = bind(args.redirect_uri)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    server.timeout = args.timeout
    state = secrets.token_urlsafe(16)
    url = auth_url(client_id, redirect_uri, state)

    print("Opening the consent screen. Sign in as an account with Content")
    print(f"manager on the Shared Drive.\nRedirect: {redirect_uri}\n")
    print(f"If no browser opens, go to:\n{url}\n")
    webbrowser.open(url)

    try:
        code = wait_for_code(server, state)
        token = exchange(code, client_id, secret, redirect_uri)
    except (RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        server.server_close()

    print("Authorised. Put this line in .env:\n")
    print(f"{REFRESH_TOKEN_ENV}={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
