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
    "about a product came in September 2025', and follow-ups such as 'Скільки з цих "
    "повідомлень стосувалось запитів по продукції і замовленню'. "
    "The tool finds the messages and/or comments of the period (`from`/`to`) that match "
    "`query`: with both, those of the period close in meaning to the query; with a period "
    "alone, all of the period; with a query alone, matches from the whole history. It "
    "returns at most 50 of each, the closest first (the newest first without a query), "
    "plus `totalMessagesCount` (conversations among all matches, each customer once "
    "however many days they wrote) and `totalCommentsCount` (comments among all matches). "
    "Answer 'how many' from the totals, not by counting the items. With a query the "
    "match is by meaning, so the totals are an estimate: say so, and use the items to "
    "check what was counted. "
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
                "2026-05-01T00:00:00. Give it when the user names a period, or refers to "
                "earlier results ('these messages', 'з цих повідомлень', 'of them'): then "
                "reuse the period of the previous search_messaging call. Resolve a named "
                "period against today's date: "
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
                "('since March', 'last 30 days') or no period was named. Reuse the previous "
                "call's `to` when the user refers to earlier results."
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
                "The topic the messages or comments must be about, as a short standalone "
                "phrase in the language of the messages (Ukrainian), e.g. 'заспокійливі "
                "добавки для собак'. Set it whenever the request names a topic, also "
                "together with a period: 'Скільки з цих повідомлень стосувалось запитів по "
                "продукції і замовленню, виключаючи співпраці та рекламу' -> 'запити щодо "
                "продукції, цін і замовлень'. Name only what to find: the search matches "
                "meaning, so 'not X' or 'excluding X' would find X -- drop exclusions "
                "('виключаючи співпраці та рекламу') and apply them yourself when reading "
                "the items. Drop counting words ('скільки', 'how many'), the period and the "
                "words 'messages'/'comments'. Leave it empty only when the user wants every "
                "message of a period, with no topic ('how many messages in June')."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Messages and/or comments of a period matching a query, at most 50 of each, with totals."""
    body: dict[str, Any] = {"messageType": messageType}
    for name, value in (("from", from_), ("to", to), ("query", query)):
        if value and value.strip():
            body[name] = value.strip()
    if "from" not in body and "to" not in body and "query" not in body:
        raise ToolError("give a period (from/to) or a query")

    search_api.log_call(NAME, body)
    return await search_api.post("/searchMessaging", body)
