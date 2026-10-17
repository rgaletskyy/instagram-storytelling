"""The Instagram Graph API client, against a fake graph.facebook.com."""

from datetime import UTC, datetime

import httpx
import pytest

from infrastructure.instagram_meta_client import (
    FEED_METRICS,
    REELS_METRICS,
    STORY_METRICS,
    InstagramMedia,
    InstagramMetaClient,
    MetaApiError,
)

pytestmark = pytest.mark.unit

BASE = "https://graph.facebook.com/v23.0"


def _client(handler, **kwargs):
    kwargs.setdefault("access_token", "token")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return InstagramMetaClient(http, graph_version="v23.0", **kwargs)


def _media(product="FEED", media_id="m1"):
    return InstagramMedia(media_id, "IMAGE", product, datetime(2026, 10, 1, tzinfo=UTC))


async def test_the_instagram_account_is_found_through_the_facebook_page():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"instagram_business_account": {"id": "1784"}, "id": "p1"})

    client = _client(handler, facebook_page_id="p1")

    assert await client.instagram_user_id() == "1784"
    assert await client.instagram_user_id() == "1784"
    assert len(seen) == 1
    assert str(seen[0].url) == f"{BASE}/p1?fields=instagram_business_account"
    assert seen[0].headers["authorization"] == "Bearer token"


async def test_a_page_without_a_linked_instagram_account_is_an_error():
    client = _client(lambda request: httpx.Response(200, json={"id": "p1"}), facebook_page_id="p1")

    with pytest.raises(MetaApiError, match="no linked Instagram"):
        await client.instagram_user_id()


async def test_media_follow_pages_and_stop_at_the_first_older_than_since():
    pages = {
        f"{BASE}/1784/media": {
            "data": [
                {"id": "a", "media_type": "VIDEO", "media_product_type": "REELS",
                 "timestamp": "2026-10-10T09:00:00+0000", "permalink": "https://ig/a"},
            ],
            "paging": {"next": f"{BASE}/1784/media?after=c1"},
        },
        f"{BASE}/1784/media?after=c1": {
            "data": [
                {"id": "b", "media_type": "CAROUSEL_ALBUM", "media_product_type": "FEED",
                 "timestamp": "2026-10-02T09:00:00+0000"},
                {"id": "c", "media_type": "IMAGE", "media_product_type": "FEED",
                 "timestamp": "2026-09-20T09:00:00+0000"},
            ],
            "paging": {"next": f"{BASE}/1784/media?after=c2"},
        },
    }  # fmt: skip

    def handler(request):
        url = str(request.url).split("&fields")[0].split("?fields")[0]
        return httpx.Response(200, json=pages[url])

    media = await _client(handler, instagram_user_id="1784").list_media(
        since=datetime(2026, 10, 1, tzinfo=UTC)
    )

    assert [(m.id, m.media_product_type) for m in media] == [("a", "REELS"), ("b", "FEED")]
    assert media[0].timestamp == datetime(2026, 10, 10, 9, tzinfo=UTC)


@pytest.mark.parametrize(("product", "metrics"), [("FEED", FEED_METRICS), ("REELS", REELS_METRICS)])
async def test_posts_and_reels_ask_for_their_own_metrics_and_skip_missing_values(product, metrics):
    seen = []

    def handler(request):
        seen.append(request.url.params)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"name": "views", "period": "lifetime", "values": [{"value": 120}]},
                    {"name": "reach", "total_value": {"value": 90}},
                    {"name": "saved", "values": []},
                ]
            },
        )

    insights = await _client(handler).media_insights(_media(product))

    assert seen[0]["metric"] == ",".join(metrics)
    assert insights.metrics == {"views": 120, "reach": 90}
    assert insights.navigation == {} and insights.unavailable is None


async def test_a_story_also_reads_its_navigation_broken_down_by_action():
    def handler(request):
        if request.url.params["metric"] == "navigation":
            assert request.url.params["breakdown"] == "story_navigation_action_type"
            breakdown = {
                "dimension_keys": ["story_navigation_action_type"],
                "results": [
                    {"dimension_values": ["tap_forward"], "value": 12},
                    {"dimension_values": ["tap_exit"], "value": 3},
                ],
            }
            return httpx.Response(
                200,
                json={"data": [{"name": "navigation",
                                "total_value": {"value": 15, "breakdowns": [breakdown]}}]},
            )  # fmt: skip
        assert request.url.params["metric"] == ",".join(STORY_METRICS)
        return httpx.Response(200, json={"data": [{"name": "replies", "values": [{"value": 0}]}]})

    insights = await _client(handler).media_insights(_media("STORY"))

    assert insights.metrics == {"replies": 0, "navigation": 15}
    assert insights.navigation == {"tap_forward": 12, "tap_exit": 3}


async def test_a_story_with_too_few_viewers_has_no_insights_rather_than_failing():
    error = {"error": {"message": "Not enough viewers", "code": 10}}
    client = _client(lambda request: httpx.Response(400, json=error))

    insights = await client.media_insights(_media("STORY"))

    assert insights.metrics == {} and "Not enough viewers" in insights.unavailable


async def test_other_graph_errors_are_raised_with_their_code():
    error = {"error": {"message": "Invalid OAuth access token", "code": 190}}
    client = _client(lambda request: httpx.Response(400, json=error))

    with pytest.raises(MetaApiError, match="Invalid OAuth") as raised:
        await client.media_insights(_media())
    assert raised.value.code == 190


async def test_nothing_is_sent_without_a_token(monkeypatch):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    client = InstagramMetaClient(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("sent"))),
        access_token="",
        instagram_user_id="1784",
    )

    with pytest.raises(MetaApiError, match="META_ACCESS_TOKEN"):
        await client.list_stories()
