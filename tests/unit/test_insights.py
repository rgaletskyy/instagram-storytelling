"""Content insights: rows of `organic`, the weekly sync, BigQuery, ContentInsightsService."""

from datetime import UTC, datetime

import pytest
from google.api_core import exceptions as google_exceptions

from domain.content_insights_service import ContentInsightsService
from domain.contracts import InvalidArgument
from infrastructure.bigquery_client import ORGANIC_COLUMNS, BigQueryClient, BigQueryError
from infrastructure.instagram_meta_client import InstagramMedia, MediaInsights, MetaApiError
from routines.insights_sync.rows import organic_row
from routines.insights_sync.sync import sync

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def _media(media_id="m1", product="FEED", **kwargs):
    return InstagramMedia(media_id, "IMAGE", product, datetime(2026, 10, 1, tzinfo=UTC), **kwargs)


# --- Rows ----------------------------------------------------------------------


def test_a_row_has_every_column_and_metrics_under_their_column_names():
    row = organic_row(
        _media(product="REELS", permalink="https://ig/p", caption="Лапи"),
        {"views": 120, "total_interactions": 9.0, "reels_skip_rate": 34, "ig_reels_avg_watch_time": 4210},
    )  # fmt: skip

    assert set(row) == set(ORGANIC_COLUMNS)
    assert (row["views"], row["totalInteractions"]) == (120, 9)
    assert isinstance(row["totalInteractions"], int)
    assert row["reelSkipRate"] == 34.0 and isinstance(row["reelSkipRate"], float)
    assert row["reelAvgWatchTime"] == 4210
    assert (row["permaLink"], row["caption"], row["mediaUrl"]) == ("https://ig/p", "Лапи", None)
    # No value from the API is no value here, not 0.
    assert row["reach"] is None and row["likes"] is None


def test_a_long_caption_is_cut_but_a_long_url_is_dropped():
    row = organic_row(_media(caption="a" * 3000, media_url="https://cdn/" + "x" * 300), {})

    assert row["caption"] == "a" * 2500
    assert row["mediaUrl"] is None


# --- Sync ----------------------------------------------------------------------


class _Meta:
    def __init__(self, media, refused=()):
        self.media, self.refused = media, set(refused)
        self.since = None

    async def list_media(self, since=None):
        self.since = since
        return self.media

    async def media_insights(self, media):
        if media.id in self.refused:
            raise MetaApiError("Media posted before business account conversion", code=100)
        return MediaInsights(media.id, metrics={"views": 10})


class _BigQuery:
    def __init__(self, rows=(), error=None):
        self.merged, self.rows, self.error, self.queries = [], list(rows), error, []

    async def merge_organic(self, rows):
        if self.error:
            raise self.error
        self.merged.extend(rows)
        return len(rows)

    async def query_organic(self, since, until, **kwargs):
        self.queries.append({"since": since, "until": until, **kwargs})
        if self.error:
            raise self.error
        return self.rows


async def test_the_sync_merges_the_last_30_days_of_posts_and_reels_and_skips_refusals():
    meta = _Meta([_media("a"), _media("b", "REELS"), _media("s", "STORY"), _media("old")],
                 refused={"old"})  # fmt: skip
    bigquery = _BigQuery()

    summary = await sync(meta, bigquery, now=NOW)

    assert meta.since == datetime(2026, 9, 17, 12, tzinfo=UTC)
    assert [row["id"] for row in bigquery.merged] == ["a", "b"]
    assert bigquery.merged[0]["views"] == 10
    assert (summary.merged, summary.failed) == (2, 1)


async def test_a_bigquery_failure_fails_the_sync():
    with pytest.raises(BigQueryError):
        await sync(_Meta([_media()]), _BigQuery(error=BigQueryError("accessDenied", "no")), now=NOW)


# --- BigQueryClient ------------------------------------------------------------


class _Job:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return self.rows


class _Row(dict):
    pass


class _Client:
    project = "proj"

    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []

    def query(self, sql, job_config):
        self.calls.append((sql, {p.name: p for p in job_config.query_parameters}))
        if self.error:
            raise self.error
        return _Job(self.rows)


async def test_merge_updates_or_inserts_by_id_within_the_rows_partitions():
    client = _Client()
    rows = [organic_row(_media("a"), {"views": 1}),
            organic_row(InstagramMedia("b", "IMAGE", "FEED", datetime(2026, 9, 2, tzinfo=UTC)), {})]  # fmt: skip

    assert await BigQueryClient(client).merge_organic(rows) == 2

    ((sql, params),) = client.calls
    assert sql.startswith("MERGE `proj.instagram_insights.organic` T")
    assert "ON T.id = S.id AND T.timestamp >= @since" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql and "`views` = S.`views`" in sql
    assert params["since"].value == datetime(2026, 9, 2, tzinfo=UTC)
    assert len(params["rows"].values) == 2


async def test_merging_nothing_runs_nothing():
    client = _Client()
    assert await BigQueryClient(client).merge_organic([]) == 0
    assert client.calls == []


async def test_query_filters_by_the_given_values_and_sorts_most_first():
    client = _Client(rows=[_Row(id="a")])

    rows = await BigQueryClient(client, dataset="ds").query_organic(
        NOW, NOW, media_product_type="REELS", sort_by="views"
    )

    ((sql, params),) = client.calls
    assert rows == [{"id": "a"}]
    assert "FROM `proj.ds.organic`" in sql
    assert (
        "timestamp >= @since AND timestamp <= @until AND mediaProductType = @mediaProductType"
        in sql
    )
    assert "mediaType = @mediaType" not in sql
    assert sql.endswith("ORDER BY `views` DESC NULLS LAST")
    assert params["mediaProductType"].value == "REELS"


async def test_query_sorts_newest_first_by_default_and_refuses_unknown_columns():
    client = _Client()
    await BigQueryClient(client).query_organic(NOW, NOW)
    assert client.calls[0][0].endswith("ORDER BY `timestamp` DESC NULLS LAST")

    with pytest.raises(ValueError):
        await BigQueryClient(client).query_organic(NOW, NOW, sort_by="views; DROP TABLE x")


async def test_bigquery_errors_carry_their_reason():
    error = google_exceptions.BadRequest(
        "Cannot query over table without a filter", errors=[{"reason": "invalidQuery"}]
    )

    with pytest.raises(BigQueryError) as raised:
        await BigQueryClient(_Client(error=error)).query_organic(NOW, NOW)
    assert raised.value.code == "invalidQuery"


# --- ContentInsightsService ----------------------------------------------------


async def test_the_service_passes_filters_and_returns_items_in_contract_names():
    row = {"id": "a", "timestamp": NOW, "mediaType": "VIDEO", "mediaProductType": "REELS",
           "permaLink": "https://ig/a", "views": 5, "totalInteractions": 2, "link_clicks": None,
           "reelSkipRate": 12.5}  # fmt: skip
    bigquery = _BigQuery(rows=[row])

    result = await ContentInsightsService(bigquery).query_content_insights(
        datetime(2026, 10, 1), media_type="VIDEO", media_product_type="REELS", sort_by="views"
    )

    (query,) = bigquery.queries
    assert query["since"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert query["until"].tzinfo is not None
    assert (query["media_type"], query["media_product_type"], query["sort_by"]) == (
        "VIDEO", "REELS", "views",
    )  # fmt: skip
    body = result.model_dump(by_alias=True)
    assert body["errorCode"] is None
    item = body["items"][0]
    assert (item["permaLink"], item["totalInteractions"], item["reelSkipRate"]) == (
        "https://ig/a",
        2,
        12.5,
    )
    assert "link_clicks" in item and item["likes"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sort_by": "likes"},
        {"media_type": "REEL"},
        {"media_product_type": "feed"},
        {"to": datetime(2026, 9, 1, tzinfo=UTC)},
    ],
)
async def test_invalid_parameters_are_refused_before_querying(kwargs):
    bigquery = _BigQuery()
    with pytest.raises(InvalidArgument):
        await ContentInsightsService(bigquery).query_content_insights(
            datetime(2026, 10, 1, tzinfo=UTC), **kwargs
        )
    assert bigquery.queries == []


async def test_a_bigquery_failure_comes_back_in_the_error_fields():
    bigquery = _BigQuery(error=BigQueryError("accessDenied", "Permission bigquery.jobs.create"))

    result = await ContentInsightsService(bigquery).query_content_insights(NOW)

    assert result.items == []
    assert (result.error_code, result.error_message) == (
        "accessDenied", "Permission bigquery.jobs.create",
    )  # fmt: skip
