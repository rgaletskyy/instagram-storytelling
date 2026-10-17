"""Instagram media and their insights, from Meta's Graph API.

The Instagram API with Facebook Login: host graph.facebook.com, an Instagram
professional account linked to a Facebook Page, and a long-lived user token
with instagram_basic, instagram_manage_insights and pages_read_engagement. It
covers more insights than the Instagram Login path (graph.instagram.com).

What the API does that callers should know:
- A story and its insights exist for 24 hours only; read them before then.
- Data can lag up to 48 hours, and missing data comes back as no value, not 0.
- A story with fewer than 5 viewers has no insights (error code 10).
- Numbers are organic only; carousels report for the album, not its items.
- `impressions` and `plays` are gone in favour of `views`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

import httpx

GRAPH_VERSION = "v23.0"
GRAPH_VERSION_ENV = "META_GRAPH_VERSION"
ACCESS_TOKEN_ENV = "META_ACCESS_TOKEN"
# Either names the account: the Instagram user id itself, or the Facebook
# Page it is linked to.
INSTAGRAM_USER_ID_ENV = "INSTAGRAM_USER_ID"
FACEBOOK_PAGE_ID_ENV = "FACEBOOK_PAGE_ID"
TIMEOUT = 30.0
PAGE_SIZE = 50

MEDIA_FIELDS = (
    "id,media_type,media_product_type,timestamp,permalink,caption,media_url,thumbnail_url"
)
# Per media product type, as specs/meta/insights.md lists them. A request with
# a metric the type does not support fails as a whole.
FEED_METRICS = (
    "views",
    "reach",
    "likes",
    "comments",
    "shares",
    "saved",
    "reposts",
    "total_interactions",
    "profile_visits",
    "follows",
)
REELS_METRICS = (
    "views",
    "reach",
    "likes",
    "comments",
    "shares",
    "saved",
    "reposts",
    "total_interactions",
    "ig_reels_avg_watch_time",
    "ig_reels_video_view_total_time",
    "reels_skip_rate",
)
STORY_METRICS = (
    "views",
    "reach",
    "replies",
    "shares",
    "reposts",
    "total_interactions",
    "profile_visits",
    "follows",
    "link_clicks",
)
# Asked apart from the rest: only it takes this breakdown.
NAVIGATION_BREAKDOWN = "story_navigation_action_type"
# Graph error code for a story with too few viewers to report on.
NOT_ENOUGH_VIEWERS = 10


class MetaApiError(RuntimeError):
    """The Graph API refused a request or could not be reached."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InstagramMedia:
    id: str
    media_type: str  # IMAGE, VIDEO, CAROUSEL_ALBUM
    media_product_type: str  # FEED, REELS, STORY, AD
    timestamp: datetime
    permalink: str = ""
    caption: str = ""
    media_url: str = ""
    thumbnail_url: str = ""


@dataclass(frozen=True)
class MediaInsights:
    media_id: str
    # Metric name to value. A metric with no data is left out, never 0.
    metrics: dict[str, float] = field(default_factory=dict)
    # Stories only: the `navigation` total split by action, e.g. TAP_FORWARD.
    navigation: dict[str, float] = field(default_factory=dict)
    # Why there are no insights at all, e.g. a story with too few viewers.
    unavailable: str | None = None


class InstagramMetaClient:
    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        access_token: str | None = None,
        instagram_user_id: str | None = None,
        facebook_page_id: str | None = None,
        graph_version: str | None = None,
    ) -> None:
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT)
        self._token = access_token or os.environ.get(ACCESS_TOKEN_ENV, "")
        self._user_id = instagram_user_id or os.environ.get(INSTAGRAM_USER_ID_ENV) or None
        self._page_id = facebook_page_id or os.environ.get(FACEBOOK_PAGE_ID_ENV) or None
        version = graph_version or os.environ.get(GRAPH_VERSION_ENV) or GRAPH_VERSION
        self._base = f"https://graph.facebook.com/{version}"

    async def instagram_user_id(self) -> str:
        """The Instagram account's id, looked up from the Facebook Page if not given."""
        if self._user_id:
            return self._user_id
        if not self._page_id:
            raise MetaApiError(f"set {INSTAGRAM_USER_ID_ENV} or {FACEBOOK_PAGE_ID_ENV}")
        page = await self._get(self._page_id, fields="instagram_business_account")
        account = page.get("instagram_business_account") or {}
        if not account.get("id"):
            raise MetaApiError(
                f"Facebook Page {self._page_id} has no linked Instagram professional account"
            )
        self._user_id = account["id"]
        return self._user_id

    async def list_media(self, since: datetime | None = None) -> list[InstagramMedia]:
        """Feed posts and reels, newest first; only those from `since` on, when given.

        `since` must be timezone-aware, as the API's timestamps are.
        """
        user_id = await self.instagram_user_id()
        media = []
        async for item in self._paged(f"{user_id}/media", fields=MEDIA_FIELDS, limit=PAGE_SIZE):
            parsed = _media(item)
            # The API lists newest first, so the first older one ends the list.
            if since and parsed.timestamp < since:
                break
            media.append(parsed)
        return media

    async def list_stories(self) -> list[InstagramMedia]:
        """The stories still live, i.e. from the last 24 hours."""
        user_id = await self.instagram_user_id()
        return [
            _media(item) async for item in self._paged(f"{user_id}/stories", fields=MEDIA_FIELDS)
        ]

    async def media_insights(self, media: InstagramMedia) -> MediaInsights:
        """Lifetime insights of one post, reel or story, picked by its kind."""
        product = media.media_product_type
        metrics = {
            "REELS": REELS_METRICS,
            "STORY": STORY_METRICS,
        }.get(product, FEED_METRICS)
        try:
            body = await self._get(f"{media.id}/insights", metric=",".join(metrics))
            values, navigation = _values(body), {}
            if product == "STORY":
                breakdown = await self._get(
                    f"{media.id}/insights",
                    metric="navigation",
                    breakdown=NAVIGATION_BREAKDOWN,
                    metric_type="total_value",
                )
                # The total lands among the metrics, the split in `navigation`.
                values.update(_values(breakdown))
                navigation = _breakdown(breakdown)
        except MetaApiError as exc:
            if exc.code == NOT_ENOUGH_VIEWERS:
                return MediaInsights(media.id, unavailable=str(exc))
            raise
        return MediaInsights(media.id, metrics=values, navigation=navigation)

    async def media(self, media_id: str) -> InstagramMedia:
        """One post, reel or story by its id."""
        return _media(await self._get(media_id, fields=MEDIA_FIELDS))

    async def _get(self, path_or_url: str, **params) -> dict:
        url = path_or_url if path_or_url.startswith("https://") else f"{self._base}/{path_or_url}"
        if not self._token:
            raise MetaApiError(f"{ACCESS_TOKEN_ENV} is not set")
        try:
            # In the header, so the token stays out of URLs and their logs.
            response = await self._http.get(
                url, params=params or None, headers={"Authorization": f"Bearer {self._token}"}
            )
        except httpx.HTTPError as exc:
            raise MetaApiError(f"the Graph API could not be reached: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error or "error" in body:
            error = body.get("error") or {}
            message = error.get("error_user_msg") or error.get("message") or response.text
            raise MetaApiError(
                f"Graph API {response.status_code}: {message}", code=error.get("code")
            )
        return body

    async def _paged(self, path: str, **params) -> AsyncIterator[dict]:
        body = await self._get(path, **params)
        while True:
            for item in body.get("data", []):
                yield item
            # `next` is a full URL carrying the original query and a cursor.
            next_url = body.get("paging", {}).get("next")
            if not next_url:
                return
            body = await self._get(next_url)


def _media(item: dict) -> InstagramMedia:
    return InstagramMedia(
        id=item["id"],
        media_type=item.get("media_type", ""),
        media_product_type=item.get("media_product_type", ""),
        # Graph writes the offset as +0000, which fromisoformat reads.
        timestamp=datetime.fromisoformat(item["timestamp"]),
        permalink=item.get("permalink", ""),
        caption=item.get("caption", ""),
        media_url=item.get("media_url", ""),
        thumbnail_url=item.get("thumbnail_url", ""),
    )


def _values(body: dict) -> dict[str, float]:
    """Each metric's value, from `values` or `total_value`; one with neither is left out."""
    metrics = {}
    for metric in body.get("data", []):
        if metric.get("values"):
            value = metric["values"][0].get("value")
        else:
            value = (metric.get("total_value") or {}).get("value")
        if value is not None:
            metrics[metric["name"]] = value
    return metrics


def _breakdown(body: dict) -> dict[str, float]:
    """A broken-down metric's value per dimension, e.g. {"TAP_FORWARD": 12}."""
    values = {}
    for metric in body.get("data", []):
        for breakdown in (metric.get("total_value") or {}).get("breakdowns", []):
            for result in breakdown.get("results", []):
                values[result["dimension_values"][0]] = result["value"]
    return values
