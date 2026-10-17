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
SORT_COLUMNS = ("views", "reach", "totalInteractions", "shares", "reposts")


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
    ) -> ContentInsights:
        """Content published between `from_` and `to` (now, when absent), both inclusive.

        Narrowed by `media_type` and `media_product_type` when given, sorted
        by `sort_by` descending (newest first without it). A BigQuery failure
        comes back in `errorCode` / `errorMessage`, not raised.
        """
        since, until = _utc(from_), _utc(to) if to else datetime.now(UTC)
        if until < since:
            raise InvalidArgument("to must not be before from")
        _check("mediaType", media_type, MEDIA_TYPES)
        _check("mediaProductType", media_product_type, MEDIA_PRODUCT_TYPES)
        _check("sortBy", sort_by, SORT_COLUMNS)
        try:
            rows = await self._bigquery.query_organic(
                since,
                until,
                media_type=media_type or None,
                media_product_type=media_product_type or None,
                sort_by=sort_by or None,
            )
        except BigQueryError as exc:
            return ContentInsights(error_code=exc.code, error_message=exc.message)
        return ContentInsights(items=[ContentInsight.model_validate(row) for row in rows])


def _check(name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    if value and value not in allowed:
        raise InvalidArgument(f"{name} must be one of {', '.join(allowed)}, got {value!r}")


def _utc(moment: datetime) -> datetime:
    """A naive datetime is taken as UTC, as BigQuery's TIMESTAMP is."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
