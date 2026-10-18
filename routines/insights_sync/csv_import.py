"""Rows of `organic` from Meta Business Suite's Instagram content exports.

The initial load (specs/instagram-insights-rag.md): the Graph API lists only
current media, and stories not at all once expired, so the history comes from
the CSV exports instead. Each export's columns differ, and an export may mix
kinds, so the kind of each row is read from its "Post type", not its file.

    uv run insights-sync --csv FILE... [--types FEED,REELS]
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from infrastructure.instagram_meta_client import InstagramMedia

from .rows import organic_row

logger = logging.getLogger(__name__)

# Business Suite writes "Publish time" in US Pacific time, whatever the
# account's zone (checked against the time in the stories' Instagram ids).
EXPORT_ZONE = ZoneInfo("America/Los_Angeles")
TIME_FORMAT = "%m/%d/%Y %H:%M"

# "Post type" to (mediaProductType, mediaType); a story's mediaType depends on
# its duration.
POST_TYPES = {
    "IG image": ("FEED", "IMAGE"),
    "IG carousel": ("FEED", "CAROUSEL_ALBUM"),
    "IG reel": ("REELS", "VIDEO"),
    "IG story": ("STORY", None),
}
# Export column to Graph API metric name. "Sticker taps" has no column.
METRICS = {
    "Views": "views",
    "Reach": "reach",
    "Likes": "likes",
    "Comments": "comments",
    "Saves": "saved",
    "Shares": "shares",
    "Follows": "follows",
    "Profile visits": "profile_visits",
    "Replies": "replies",
    "Link clicks": "link_clicks",
    "Navigation": "navigation",
}


def csv_rows(paths: Iterable[Path]) -> list[dict]:
    """The rows of every export, by id; a media in two exports appears once."""
    rows = {}
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as file:
            for record in csv.DictReader(file):
                row = _row(record)
                if row:
                    rows[row["id"]] = row
    return list(rows.values())


def _row(record: dict) -> dict | None:
    kind = POST_TYPES.get(record["Post type"])
    if not kind:
        logger.warning("%s: unknown post type %r, skipped", record["Post ID"], record["Post type"])
        return None
    product, media_type = kind
    if media_type is None:
        media_type = "VIDEO" if int(record["Duration (sec)"] or 0) else "IMAGE"
    media = InstagramMedia(
        record["Post ID"],
        media_type,
        product,
        datetime.strptime(record["Publish time"], TIME_FORMAT)
        .replace(tzinfo=EXPORT_ZONE)
        .astimezone(UTC),
        record["Permalink"] or None,
        record["Description"] or None,
    )
    # Exports leave out a record's trailing empty columns, hence `or ""`.
    metrics = {
        metric: int(record[column])
        for column, metric in METRICS.items()
        if (record.get(column) or "").strip()
    }
    return organic_row(media, metrics)
