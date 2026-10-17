"""Copies the insights of recent Instagram posts and reels into BigQuery.

Run weekly (specs/instagram-insights-rag.md, "Sync job"): it reads every post
and reel published in the last `--days` days (30 by default), asks the Graph
API for each one's lifetime insights, and merges them into `organic` by id, so
a post read again gets its newer numbers. Stories are not read here: they
expire after 24 hours and reach BigQuery through the webhook instead.

    uv run insights-sync [--days N]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from infrastructure.bigquery_client import BigQueryClient
from infrastructure.instagram_meta_client import InstagramMetaClient, MetaApiError

from .rows import organic_row

logger = logging.getLogger(__name__)

DAYS = 30
# Insights requests in flight at once.
CONCURRENCY = 5


@dataclass
class SyncSummary:
    merged: int = 0
    failed: int = 0  # media whose insights the API refused


async def sync(
    meta: InstagramMetaClient,
    bigquery: BigQueryClient,
    days: int = DAYS,
    now: datetime | None = None,
) -> SyncSummary:
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    media = [m for m in await meta.list_media(since=since) if m.media_product_type != "STORY"]
    gate = asyncio.Semaphore(CONCURRENCY)
    summary = SyncSummary()

    async def row_of(item):
        async with gate:
            try:
                insights = await meta.media_insights(item)
            except MetaApiError as exc:
                # One post's refusal (e.g. published before the account went
                # professional) should not cost the others theirs.
                logger.warning("no insights for %s: %s", item.id, exc)
                summary.failed += 1
                return None
        return organic_row(item, insights.metrics)

    rows = [row for row in await asyncio.gather(*map(row_of, media)) if row]
    summary.merged = await bigquery.merge_organic(rows)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insights-sync", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days", type=int, default=DAYS, help=f"how far back to read (default: {DAYS})"
    )
    args = parser.parse_args(argv)

    from infrastructure.env import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    summary = asyncio.run(sync(InstagramMetaClient(), BigQueryClient(), days=args.days))
    print(f"organic: {summary.merged} merged, {summary.failed} without insights")
    return 0


if __name__ == "__main__":
    sys.exit(main())
