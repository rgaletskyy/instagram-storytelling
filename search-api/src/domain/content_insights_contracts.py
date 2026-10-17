"""ContentInsightsService data contracts. Mirrors specs/content-insights-service.md.

Fields are named as the columns of the BigQuery table `organic`
(specs/instagram-insights-rag.md), `link_clicks` included.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ContentInsight(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    id: str
    timestamp: datetime
    media_type: str
    media_product_type: str
    caption: str | None = None
    media_url: str | None = None
    thumbnail_url: str | None = None
    perma_link: str | None = None
    # Metrics: None where the API had no value, which is not the same as 0.
    views: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    saved: int | None = None
    shares: int | None = None
    reposts: int | None = None
    total_interactions: int | None = None
    profile_visits: int | None = None
    follows: int | None = None
    replies: int | None = None
    link_clicks: int | None = Field(default=None, alias="link_clicks")
    navigation: int | None = None
    reel_avg_watch_time: int | None = None
    reel_view_total_time: int | None = None
    reel_skip_rate: float | None = None


class ContentInsights(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: list[ContentInsight] = Field(default_factory=list)
    # Set when BigQuery failed; `items` is then empty.
    error_code: str | None = None
    error_message: str | None = None
