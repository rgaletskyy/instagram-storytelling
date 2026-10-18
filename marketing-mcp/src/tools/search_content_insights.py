"""search_content_insights: how the account's Instagram posts, reels and stories performed, via the search API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field

from . import search_api

NAME = "search_content_insights"
DESCRIPTION = (
    "Invoke this tool when the user asks how HealthyDoggo's own Instagram posts, reels, "
    "stories or ads performed: views, likes, saves, shares, reposts or interactions, "
    "usually the best ones of a period. For example: 'top 5 posts from May 2026 with the "
    "most interactions', 'two best performing posts by likes and comments between "
    "01.01.2026 and 01.04.2026', 'the post from September with the most views and shares', "
    "'the story from last week that got the most likes'. "
    "Turn the request into parameters: the period into `from`/`to`, the kind of content "
    "into `mediaProductType` (and `mediaType` only for photos, videos or carousels), the "
    "metrics into `sortBy`, most important first, and the number of items into `topN`. "
    "Each item comes back with its permalink, caption, publication time and every metric; "
    "a metric with no value is null, not 0."
)

MediaProductType = Literal["FEED", "STORY", "REELS", "AD"]
MediaType = Literal["IMAGE", "VIDEO", "CAROUSEL_ALBUM"]


async def search_content_insights(
    from_: Annotated[
        str,
        Field(
            alias="from",
            description=(
                "Start of the period the content was published in, inclusive, as an ISO 8601 "
                "datetime, e.g. 2026-05-01T00:00:00. Resolve the period the user names "
                "against today's date: 'May' = 2026-05-01T00:00:00; 'last week' = Monday "
                "00:00:00 of the previous week; 'in 2025' = 2025-01-01T00:00:00; 'last 30 "
                "days' = 30 days before now. Dates written as 01.04.2026 are day.month.year. "
                "Without a year, use the current one, or the previous one if that month has "
                "not come yet. Without any period, use the last 30 days."
            ),
        ),
    ],
    to: Annotated[
        str | None,
        Field(
            description=(
                "End of the period, inclusive, as an ISO 8601 datetime, e.g. "
                "2026-05-31T23:59:59 for 'May' or 2026-04-01T23:59:59 for 'until "
                "01.04.2026'. Leave empty when the period runs up to now ('since March', "
                "'last 30 days', 'this month')."
            )
        ),
    ] = None,
    mediaProductType: Annotated[
        MediaProductType | None,
        Field(
            description=(
                "Where the content was published. "
                '"FEED" = posts in the profile grid (photo and carousel posts); '
                '"STORY" = stories; "REELS" = reels; "AD" = ads. '
                "'Posts' means FEED. Leave empty if the user did not name a kind, or "
                "said 'content' or 'publications' in general."
            )
        ),
    ] = None,
    mediaType: Annotated[
        MediaType | None,
        Field(
            description=(
                "Format of the media. "
                '"IMAGE" = a single photo; "VIDEO" = a video (reels are always VIDEO); '
                '"CAROUSEL_ALBUM" = a carousel of several photos or videos. '
                "Leave empty unless the user explicitly asks for photos, videos or carousels."
            )
        ),
    ] = None,
    sortBy: Annotated[
        str | None,
        Field(
            description=(
                "Metrics to rank by, highest first: up to three names, comma-separated, "
                "most important first (e.g. 'views,shares'); each later one only breaks "
                "ties in the ones before it. "
                '"views" = times shown ("views", "reach", "most seen", "popular"); '
                '"totalInteractions" = likes, comments, saves, shares and replies together '
                '("interactions", "engagement", "best performing", "most active", and '
                "likes combined with comments, since comments alone cannot be sorted on); "
                '"likes" = likes; "saved" = saves; "shares" = shares; "reposts" = reposts. '
                "Leave empty to get the newest content first."
            )
        ),
    ] = None,
    topN: Annotated[
        int | None,
        Field(
            ge=1,
            description=(
                "How many items to return, taken after sorting: 'top 5 posts' = 5, 'two "
                "best' = 2, 'the post with the most views' = 1. Leave empty when the user "
                "gives no number and wants everything in the period."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """The account's content published in the period, ranked by the chosen metrics."""
    body: dict[str, Any] = {"from": from_.strip()}
    if not body["from"]:
        raise ToolError("from must not be empty")
    for name, value in (("to", to), ("sortBy", sortBy)):
        if value and value.strip():
            body[name] = value.strip()
    for name, value in (
        ("mediaProductType", mediaProductType),
        ("mediaType", mediaType),
        ("topN", topN),
    ):
        if value is not None:
            body[name] = value

    search_api.log_call(NAME, body)
    result = await search_api.post("/searchContentInsights", body)
    # The API answers 200 with the BigQuery failure in errorCode / errorMessage.
    if isinstance(result, dict) and result.get("errorCode"):
        raise ToolError(
            f"insights could not be read ({result['errorCode']}): {result.get('errorMessage')}"
        )
    return result
