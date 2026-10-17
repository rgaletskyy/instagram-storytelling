"""The `instagram_insights` BigQuery dataset: writing and reading `organic`.

`organic` holds one row per post, reel or story, partitioned by month on
`timestamp` with a partition filter required, so every statement here bounds
`timestamp`. Rows are merged by `id`: a later sync of the same media updates
its row rather than adding another.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from google.api_core import exceptions as google_exceptions
from google.auth import exceptions as auth_exceptions
from google.cloud import bigquery

DATASET_ENV = "INSIGHTS_DATASET"
DEFAULT_DATASET = "instagram_insights"
ORGANIC = "organic"

# Every column of `organic`, with its BigQuery type, in table order.
ORGANIC_COLUMNS = {
    "id": "STRING",
    "timestamp": "TIMESTAMP",
    "mediaType": "STRING",
    "mediaProductType": "STRING",
    "caption": "STRING",
    "mediaUrl": "STRING",
    "thumbnailUrl": "STRING",
    "permaLink": "STRING",
    "views": "INT64",
    "reach": "INT64",
    "likes": "INT64",
    "comments": "INT64",
    "saved": "INT64",
    "shares": "INT64",
    "reposts": "INT64",
    "totalInteractions": "INT64",
    "profileVisits": "INT64",
    "follows": "INT64",
    "replies": "INT64",
    "link_clicks": "INT64",
    "navigation": "INT64",
    "reelAvgWatchTime": "INT64",
    "reelViewTotalTime": "INT64",
    "reelSkipRate": "FLOAT64",
}
# STRING(n) columns: a longer value would fail the whole statement.
MAX_LENGTHS = {
    "mediaType": 50,
    "mediaProductType": 50,
    "caption": 2500,
    "mediaUrl": 200,
    "thumbnailUrl": 200,
}


class BigQueryError(RuntimeError):
    """BigQuery refused a statement or could not be reached."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class BigQueryClient:
    def __init__(
        self,
        client: bigquery.Client | None = None,
        dataset: str | None = None,
    ) -> None:
        # Created on first use, so building the client needs no credentials.
        self._client = client
        self._dataset = dataset or os.environ.get(DATASET_ENV) or DEFAULT_DATASET

    async def merge_organic(self, rows: list[dict]) -> int:
        """Insert or update `rows` (column name to value) by `id`; the number merged."""
        if not rows:
            return 0
        columns = list(ORGANIC_COLUMNS)
        updates = ", ".join(f"`{c}` = S.`{c}`" for c in columns if c != "id")
        names = ", ".join(f"`{c}`" for c in columns)
        values = ", ".join(f"S.`{c}`" for c in columns)
        # The `timestamp` bound satisfies the partition filter; a media's
        # timestamp never changes, so its row is always within it.
        sql = (
            "MERGE `{organic}` T "
            "USING (SELECT * FROM UNNEST(@rows)) S "
            "ON T.id = S.id AND T.timestamp >= @since "
            f"WHEN MATCHED THEN UPDATE SET {updates} "
            f"WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values})"
        )
        params = [
            bigquery.ArrayQueryParameter("rows", "STRUCT", [_struct(row) for row in rows]),
            bigquery.ScalarQueryParameter(
                "since", "TIMESTAMP", min(row["timestamp"] for row in rows)
            ),
        ]
        await self._run(sql, params)
        return len(rows)

    async def query_organic(
        self,
        since: datetime,
        until: datetime,
        media_type: str | None = None,
        media_product_type: str | None = None,
        sort_by: str | None = None,
    ) -> list[dict]:
        """Rows with `since <= timestamp <= until`, most of `sort_by` first.

        `sort_by` must be a column name; without it, the newest come first.
        Rows missing the sort value come last.
        """
        if sort_by is not None and sort_by not in ORGANIC_COLUMNS:
            raise ValueError(f"unknown column {sort_by!r}")
        where = ["timestamp >= @since", "timestamp <= @until"]
        params = [
            bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
            bigquery.ScalarQueryParameter("until", "TIMESTAMP", until),
        ]
        if media_type:
            where.append("mediaType = @mediaType")
            params.append(bigquery.ScalarQueryParameter("mediaType", "STRING", media_type))
        if media_product_type:
            where.append("mediaProductType = @mediaProductType")
            params.append(
                bigquery.ScalarQueryParameter("mediaProductType", "STRING", media_product_type)
            )
        sql = (
            f"SELECT * FROM `{{organic}}` WHERE {' AND '.join(where)} "
            f"ORDER BY `{sort_by or 'timestamp'}` DESC NULLS LAST"
        )
        return [dict(row.items()) for row in await self._run(sql, params)]

    def _bigquery(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client()
        return self._client

    async def _run(self, sql: str, params: list) -> list:
        """Run `sql`, with `{organic}` standing for the table's full name."""
        config = bigquery.QueryJobConfig(query_parameters=params)

        def run() -> list:
            client = self._bigquery()
            table = f"{client.project}.{self._dataset}.{ORGANIC}"
            return list(client.query(sql.format(organic=table), job_config=config).result())

        try:
            return await asyncio.to_thread(run)
        except google_exceptions.GoogleAPICallError as exc:
            reason = (exc.errors or [{}])[0].get("reason") or type(exc).__name__
            raise BigQueryError(reason, exc.message) from exc
        except (google_exceptions.GoogleAPIError, auth_exceptions.GoogleAuthError) as exc:
            raise BigQueryError(type(exc).__name__, str(exc)) from exc


def _struct(row: dict) -> bigquery.StructQueryParameter:
    return bigquery.StructQueryParameter(
        None,
        *(
            bigquery.ScalarQueryParameter(column, kind, row.get(column))
            for column, kind in ORGANIC_COLUMNS.items()
        ),
    )
