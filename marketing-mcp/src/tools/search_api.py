"""Calls to the search API, shared by the tools.

The API sits behind Cloud Run IAM. This server calls it as its own service
account, with an ID token from the metadata server -- no key anywhere -- and
without a user token: the API admits accounts listed in its SERVICE_CALLERS
for that.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

TIMEOUT = 60.0


def _service_token(audience: str) -> str:
    """An ID token for this server's service account, for the API's audience."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.fetch_id_token(Request(), audience)


def log_call(tool: str, fields: dict[str, Any]) -> None:
    """One JSON line per call. The API sees only this server's account; who asked is recorded here."""
    signed_in = get_access_token()
    print(
        json.dumps(
            {
                "severity": "INFO",
                "message": tool,
                "user": (signed_in.claims or {}).get("email") if signed_in else None,
                **fields,
            },
            ensure_ascii=False,
        ),
        # stderr: over stdio, stdout is the MCP channel itself.
        file=sys.stderr,
        flush=True,
    )


async def post(path: str, body: dict[str, Any]) -> Any:
    """POST `body` to the API's `path`; its JSON answer, or a ToolError with its detail."""
    api_url = os.environ.get("API_URL")
    if not api_url:
        raise ToolError("API_URL is not set")
    headers = {"Content-Type": "application/json"}
    # Unset only when calling an API that has no Cloud Run in front of it.
    audience = os.environ.get("API_AUDIENCE")
    if audience:
        try:
            token = await asyncio.to_thread(_service_token, audience)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"could not get a service token for the search API: {exc}") from exc
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{api_url.rstrip('/')}/{path.lstrip('/')}", json=body, headers=headers
            )
    except httpx.HTTPError as exc:
        raise ToolError(f"the search API could not be reached: {exc}") from exc

    try:
        result = response.json()
    except ValueError:
        result = {"detail": response.text[:500] or response.reason_phrase}
    if response.status_code != 200:
        detail = result.get("detail") if isinstance(result, dict) else result
        raise ToolError(f"search failed ({response.status_code}): {detail}")
    return result
