"""Insights of the account's own Instagram content, read from BigQuery.

Implements specs/content-insights-service.md. The rows are written by the
weekly sync (routines/insights_sync) and the story webhook (search-api/src/webhook).
"""

from __future__ import annotations

from datetime import UTC, datetime

from infrastructure.bigquery_client import BigQueryClient, BigQueryError

from .content_insights_contracts import ContentInsight, ContentInsights
from .contracts import InvalidArgument

MEDIA_TYPES = ("IMAGE", "VIDEO", "CAROUSEL_ALBUM")
MEDIA_PRODUCT_TYPES = ("FEED", "STORY", "REELS", "AD")
SORT_COLUMNS = ("views", "totalInteractions", "shares", "reposts", "likes", "saved")
MAX_SORT_COLUMNS = 3


class ContentInsightsService:
    def __init__(self, bigquery: BigQueryClient | None = None) -> None:
        self._bigquery = bigquery or BigQueryClient()

    async def query_content_insights(
        self,
        from_: datetime,
        to: datetime | None = None,
        media_type: str | None = None,
        media_product_type: str | None = None,
        sort_by: str | None = None,
        top_n: int | None = None,
    ) -> ContentInsights:
        """Content published between `from_` and `to` (now, when absent), both inclusive.

        Narrowed by `media_type` and `media_product_type` when given, sorted
        descending by the comma-separated columns of `sort_by`, each breaking
        the ties of the one before (newest first without it), and cut to the first
        `top_n` when given. A BigQuery failure
        comes back in `errorCode` / `errorMessage`, not raised.
        """
        since, until = _utc(from_), _utc(to) if to else datetime.now(UTC)
        if until < since:
            raise InvalidArgument("to must not be before from")
        _check("mediaType", media_type, MEDIA_TYPES)
        _check("mediaProductType", media_product_type, MEDIA_PRODUCT_TYPES)
        sort_columns = _sort_columns(sort_by)
        if top_n is not None and top_n < 1:
            raise InvalidArgument(f"topN must be at least 1, got {top_n}")
        try:
            rows = await self._bigquery.query_organic(
                since,
                until,
                media_type=media_type or None,
                media_product_type=media_product_type or None,
                sort_by=sort_columns,
                limit=top_n,
            )
        except BigQueryError as exc:
            return ContentInsights(error_code=exc.code, error_message=exc.message)
        return ContentInsights(items=[ContentInsight.model_validate(row) for row in rows])


def _check(name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    if value and value not in allowed:
        raise InvalidArgument(f"{name} must be one of {', '.join(allowed)}, got {value!r}")


def _sort_columns(sort_by: str | None) -> list[str]:
    """`sortBy`'s columns in priority order: "likes, saved" -> ["likes", "saved"]."""
    columns = [c.strip() for c in (sort_by or "").split(",") if c.strip()]
    for column in columns:
        _check("sortBy", column, SORT_COLUMNS)
    if len(columns) > MAX_SORT_COLUMNS:
        raise InvalidArgument(f"sortBy takes at most {MAX_SORT_COLUMNS} columns, got {sort_by!r}")
    if len(set(columns)) < len(columns):
        raise InvalidArgument(f"sortBy names a column twice: {sort_by!r}")
    return columns


def _utc(moment: datetime) -> datetime:
    """A naive datetime is taken as UTC, as BigQuery's TIMESTAMP is."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
