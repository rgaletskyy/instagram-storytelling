"""search_knowledge_base: products, Instagram conversations and content, via the search API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field

from . import search_api

NAME = "search_knowledge_base"
DESCRIPTION = (
    "Invoke this tool when user asks about product information, reviews, questions "
    "about product or explicitly asks to search for product related content. "
    "Use this tool to get extra information about product."
)

ContentType = Literal["лайфстайл", "креатив", "продуктове"]


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

    search_api.log_call(
        NAME,
        {
            "productSku": body.get("productSku"),
            "hasDog": body.get("hasDog"),
            "type": body.get("type"),
            "query": body.get("query"),
        },
    )
    return await search_api.post("/searchcontent", body)
