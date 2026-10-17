"""A row of the BigQuery table `organic` from a media and its metrics.

Shared by the weekly sync and the story webhook, so both write rows alike.
"""

from __future__ import annotations

import logging

from infrastructure.bigquery_client import MAX_LENGTHS, ORGANIC_COLUMNS
from infrastructure.instagram_meta_client import InstagramMedia

logger = logging.getLogger(__name__)

# Graph API metric name to `organic` column.
METRIC_COLUMNS = {
    "views": "views",
    "reach": "reach",
    "likes": "likes",
    "comments": "comments",
    "saved": "saved",
    "shares": "shares",
    "reposts": "reposts",
    "total_interactions": "totalInteractions",
    "profile_visits": "profileVisits",
    "follows": "follows",
    "replies": "replies",
    "link_clicks": "link_clicks",
    "navigation": "navigation",
    "ig_reels_avg_watch_time": "reelAvgWatchTime",
    "ig_reels_video_view_total_time": "reelViewTotalTime",
    "reels_skip_rate": "reelSkipRate",
}


def organic_row(media: InstagramMedia, metrics: dict[str, float]) -> dict:
    """Every column of `organic`; a metric the API had no value for is None."""
    row = {
        "id": media.id,
        "timestamp": media.timestamp,
        "mediaType": media.media_type,
        "mediaProductType": media.media_product_type,
        "caption": media.caption or None,
        "mediaUrl": media.media_url or None,
        "thumbnailUrl": media.thumbnail_url or None,
        "permaLink": media.permalink or None,
    }
    for metric, column in METRIC_COLUMNS.items():
        value = metrics.get(metric)
        if value is not None:
            value = float(value) if ORGANIC_COLUMNS[column] == "FLOAT64" else round(value)
        row[column] = value
    for column, limit in MAX_LENGTHS.items():
        value = row[column]
        if value and len(value) > limit:
            if column == "caption":
                row[column] = value[:limit]
            else:
                # A cut URL is a broken one; better none. Instagram's CDN
                # URLs are signed and often longer than the column allows.
                logger.warning("%s of %s is %d long, over %d; left empty",
                               column, media.id, len(value), limit)  # fmt: skip
                row[column] = None
    return row
