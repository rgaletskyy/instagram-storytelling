"""search_knowledge_base: products, Instagram conversations and content, via the search API.

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
from typing import Annotated, Any, Literal

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import Field

NAME = "search_knowledge_base"
DESCRIPTION = (
    "Invoke this tool when user asks about product information, reviews, questions "
    "about product or explicitly asks to search for product related content. "
    "Use this tool to get extra information about product."
)
TIMEOUT = 60.0

ContentType = Literal["лайфстайл", "креатив", "продуктове"]


def _service_token(audience: str) -> str:
    """An ID token for this server's service account, for the API's audience."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.fetch_id_token(Request(), audience)


async def search_knowledge_base(
    query: Annotated[
        str,
        Field(
            description=(
                "A standalone search query. Rewrite the customer's message so it makes "
                "sense without the conversation: replace pronouns with the product or "
                "topic they refer to, include relevant details mentioned earlier (dog "
                "age, breed, problem, lifestyle or promo photos), and drop greetings and "
                "filler. Pay attention on description what should be present on content "
                "item. Extract most important descriptions customer provides for desired "
                "content to build a target query."
            )
        ),
    ],
    productSku: Annotated[
        str | None,
        Field(
            description=(
                "Id that identifies product among others. Extract it from customer "
                "query as single string parameter."
            )
        ),
    ] = None,
    hasDog: Annotated[
        bool | None,
        Field(
            description=(
                "Specifies if content should contain a dog. Don't pass anything if it's "
                "not possible to extract it from messaging."
            )
        ),
    ] = None,
    contentType: Annotated[
        ContentType | None,
        Field(
            description=(
                "Kind of media to return. "
                '"лайфстайл" = real-life photos or videos of dogs or people using products; '
                '"креатив" = designed banners with text, prices, or buttons; '
                '"продуктове" = product-only shots on a plain background. '
                "Leave empty if the user did not indicate a kind."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Products, Instagram messages and content items close to the query."""
    if not query.strip():
        raise ToolError("query must not be empty")

    body: dict[str, Any] = {"query": query}
    if productSku and productSku.strip():
        body["productSku"] = productSku.strip()
    if hasDog is not None:
        body["hasDog"] = hasDog
    # Left out, the API searches lifestyle content: its own default.
    if contentType is not None:
        body["type"] = contentType

    # The API sees only this server's account; who asked is recorded here.
    signed_in = get_access_token()
    print(
        json.dumps(
            {
                "severity": "INFO",
                "message": "search_knowledge_base",
                "user": (signed_in.claims or {}).get("email") if signed_in else None,
                "productSku": body.get("productSku"),
                "hasDog": body.get("hasDog"),
                "type": body.get("type"),
                "query": body.get("query"),
            },
            ensure_ascii=False,
        ),
        # stderr: over stdio, stdout is the MCP channel itself.
        file=sys.stderr,
        flush=True,
    )

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
                f"{api_url.rstrip('/')}/searchcontext", json=body, headers=headers
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
