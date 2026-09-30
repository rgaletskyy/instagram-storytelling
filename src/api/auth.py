"""Who is calling: the end user, re-checked here rather than taken on trust.

Two layers guard the API. Cloud Run itself admits only requests carrying an ID
token for the marketing portal's service account (--no-allow-unauthenticated,
roles/run.invoker granted to that account alone); that proves the portal sent
the request, and never reaches this code. On top of it the portal forwards the
signed-in user's own Google ID token in `X-User-Token`, and this module
verifies it: Google's signature, the portal's OAuth client as audience, a
verified email on the allowlist. A plain email header would prove nothing --
anything holding the service account's token could claim to be anyone.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request, status
from google.auth.exceptions import GoogleAuthError, TransportError

logger = logging.getLogger("api")

USER_TOKEN_HEADER = "X-User-Token"
# The portal's Google OAuth client id, which Google puts in the user's ID token
# as `aud`. Comma-separated, so a second client (a local one for development)
# can be allowed alongside it.
AUDIENCE_ENV = "USER_TOKEN_AUDIENCE"
# Emails allowed to call the API, comma-separated.
ALLOWED_USERS_ENV = "ALLOWED_USERS"


@dataclass(frozen=True)
class AuthSettings:
    audiences: tuple[str, ...]
    allowed_users: frozenset[str]

    @classmethod
    def from_env(cls) -> AuthSettings:
        audiences = tuple(_split(os.environ.get(AUDIENCE_ENV, "")))
        allowed = frozenset(e.lower() for e in _split(os.environ.get(ALLOWED_USERS_ENV, "")))
        # Fail closed: an API with no audience or no allowlist would either
        # accept any Google account or refuse everyone without saying why.
        missing = [
            name
            for name, value in ((AUDIENCE_ENV, audiences), (ALLOWED_USERS_ENV, allowed))
            if not value
        ]
        if missing:
            raise RuntimeError(f"API auth is not configured: set {', '.join(missing)}")
        return cls(audiences, allowed)


@dataclass(frozen=True)
class User:
    email: str


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def verify_google_id_token(token: str, audiences: tuple[str, ...]) -> Mapping[str, Any]:
    """Google's signature, expiry, issuer and audience.

    Raises ValueError or GoogleAuthError if the token fails any of them, and
    TransportError if Google's signing certificates cannot be fetched.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), list(audiences))


def _refuse(code: int, detail: str, email: str = "") -> HTTPException:
    # Logged: a refused caller is as much a part of the audit trail as one let in.
    logger.warning(
        "refused", extra={"fields": {"user": email or None, "status": code, "reason": detail}}
    )
    return HTTPException(code, detail=detail)


def _unauthorized(detail: str) -> HTTPException:
    return _refuse(status.HTTP_401_UNAUTHORIZED, detail)


async def current_user(
    request: Request,
    x_user_token: Annotated[str | None, Header(alias=USER_TOKEN_HEADER)] = None,
) -> User:
    """FastAPI dependency: the verified, allowlisted user, or 401 / 403."""
    if not x_user_token:
        raise _unauthorized(f"missing {USER_TOKEN_HEADER}")
    settings: AuthSettings = request.app.state.auth
    try:
        # Blocking: fetches Google's signing certificates over HTTP.
        claims = await asyncio.to_thread(verify_google_id_token, x_user_token, settings.audiences)
    except TransportError as exc:
        # Not the caller's fault: Google's certificates could not be fetched.
        raise _refuse(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"cannot verify the user now: {exc}"
        ) from exc
    except (ValueError, GoogleAuthError) as exc:
        raise _unauthorized(f"invalid user token: {exc}") from exc
    email = str(claims.get("email", "")).lower()
    if not email or claims.get("email_verified") is not True:
        raise _unauthorized("user token carries no verified email")
    if email not in settings.allowed_users:
        raise _refuse(status.HTTP_403_FORBIDDEN, f"{email} is not allowed", email)
    return User(email=email)
