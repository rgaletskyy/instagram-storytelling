"""search_messaging: Instagram direct messages and comments, via the search API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field

from . import search_api

NAME = "search_messaging"
DESCRIPTION = (
    "Invoke this tool when the user asks about Instagram direct messages or comments "
    "under HealthyDoggo's posts and reels: what customers write or ask about, or how many "
    "messages or comments there were. For example: 'how many messages were sent in June "
    "2026', 'what do people ask most about Calming supplements', 'how many comments asking "
    "about a product came in September 2025'. "
    "With a period (`from` and/or `to`) the tool returns the newest 50 message items and/or "
    "50 comments in it, plus `totalMessagesCount` (conversations active in the whole "
    "period, each customer once however many days they wrote) and "
    "`totalCommentsCount` (comments in the whole period); `query` is not used. Answer 'how "
    "many' from the totals, not by counting the items. "
    "Without a period it returns the 20 message items and/or 20 comments closest to "
    "`query`, and no totals. "
    "A message item is one conversation's day: `sender` is the customer, `text` holds the "
    "day's messages from both sides, one a line as 'username: text' (HealthyDoggo's own "
    "are 'healthydoggo.ua: ...'), and `timestamp` is the day's first message. A comment "
    "item is one comment or reply, with `parentId`, the post or reel it is under."
)

MessageType = Literal["Message", "Comment", "Both"]


async def search_messaging(
    from_: Annotated[
        str | None,
        Field(
            alias="from",
            description=(
                "Start of the period, inclusive, as an ISO 8601 datetime, e.g. "
                "2026-05-01T00:00:00. Give it only when the user names a period; then the "
                "newest items of the period and its totals are returned. Resolve it against "
                "today's date: "
                "'May' = 2026-05-01T00:00:00; 'last week' = Monday 00:00:00 of the previous "
                "week; 'in 2025' = 2025-01-01T00:00:00; 'last 30 days' = 30 days before "
                "now. Dates written as 01.04.2026 are day.month.year. Without a year, use "
                "the current one, or the previous one if that month has not come yet."
            ),
        ),
    ] = None,
    to: Annotated[
        str | None,
        Field(
            description=(
                "End of the period, inclusive, as an ISO 8601 datetime, e.g. "
                "2026-05-31T23:59:59 for 'May'. Leave empty when the period runs up to now "
                "('since March', 'last 30 days') or no period was named."
            )
        ),
    ] = None,
    messageType: Annotated[
        MessageType,
        Field(
            description=(
                '"Message" = direct messages only; "Comment" = comments only; "Both" = '
                "both. Use Both when the user names neither, or names both."
            )
        ),
    ] = "Both",
    query: Annotated[
        str | None,
        Field(
            description=(
                "What the messages or comments are about, as a standalone search query, "
                "e.g. 'заспокійливі добавки для собак'. Required when no period is given; "
                "ignored with a period."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """A period's newest messages and/or comments with its totals, or the closest to a query."""
    body: dict[str, Any] = {"messageType": messageType}
    for name, value in (("from", from_), ("to", to), ("query", query)):
        if value and value.strip():
            body[name] = value.strip()
    if "from" not in body and "to" not in body and "query" not in body:
        raise ToolError("give a period (from/to) or a query")

    search_api.log_call(NAME, body)
    return await search_api.post("/searchMessaging", body)
