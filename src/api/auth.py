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
# Service accounts allowed to call with no user behind them -- the MCP server,
# which acts for an AI assistant rather than for a signed-in person. Optional:
# unset, every call needs a user token.
SERVICE_CALLERS_ENV = "SERVICE_CALLERS"
# The audience those accounts' ID tokens carry: this API's own URL.
# Comma-separated, since a Cloud Run service answers on more than one URL.
SERVICE_AUDIENCE_ENV = "SERVICE_TOKEN_AUDIENCE"


@dataclass(frozen=True)
class AuthSettings:
    audiences: tuple[str, ...]
    allowed_users: frozenset[str]
    service_callers: frozenset[str] = frozenset()
    service_audiences: tuple[str, ...] = ()

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
        callers = frozenset(e.lower() for e in _split(os.environ.get(SERVICE_CALLERS_ENV, "")))
        service_audiences = tuple(_split(os.environ.get(SERVICE_AUDIENCE_ENV, "")))
        # Half a configuration would let a service in with no audience check,
        # or name accounts that could never get in.
        if bool(callers) != bool(service_audiences):
            raise RuntimeError(
                f"set both {SERVICE_CALLERS_ENV} and {SERVICE_AUDIENCE_ENV}, or neither"
            )
        return cls(audiences, allowed, callers, service_audiences)


@dataclass(frozen=True)
class User:
    """Who acted: a signed-in person, or a service account calling for itself."""

    email: str
    is_service: bool = False


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
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """FastAPI dependency: the verified, allowlisted caller, or 401 / 403.

    A user token, when sent, decides: the portal always acts for a person.
    Without one, the caller's own service token is checked against
    SERVICE_CALLERS -- but only when that list is configured.
    """
    settings: AuthSettings = request.app.state.auth
    if not x_user_token:
        if settings.service_callers and authorization:
            return await _service_caller(authorization, settings)
        raise _unauthorized(f"missing {USER_TOKEN_HEADER}")
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


async def _service_caller(authorization: str, settings: AuthSettings) -> User:
    """The service account behind a Bearer ID token, if it may call without a user.

    Cloud Run has already checked this token before the request got here; it
    is verified again so the API does not rest on how the service is deployed.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized(f"missing {USER_TOKEN_HEADER}")
    try:
        claims = await asyncio.to_thread(
            verify_google_id_token, token.strip(), settings.service_audiences
        )
    except TransportError as exc:
        raise _refuse(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"cannot verify the caller now: {exc}"
        ) from exc
    except (ValueError, GoogleAuthError) as exc:
        raise _unauthorized(f"invalid service token: {exc}") from exc
    email = str(claims.get("email", "")).lower()
    if not email or claims.get("email_verified") is not True:
        raise _unauthorized("service token carries no verified email")
    if email not in settings.service_callers:
        raise _refuse(status.HTTP_403_FORBIDDEN, f"{email} may not call without a user", email)
    return User(email=email, is_service=True)
