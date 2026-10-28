"""Copies the last three weeks of Instagram direct messages and comments into Firestore.

Run weekly: it reads every direct message and every comment of the last
`--days` days (21 by default) from the Graph API, embeds them like rag-index
does, and stores what is new.

- Messages go to `instagram_messages` in its RAG shape: one document per
  conversation and Kyiv day, both sides (routines.vector_indexer.message_documents).
  The window starts at a Kyiv midnight, so every day read is read whole, and a
  day that gained messages since the last run is embedded and written again.
- Comments and their replies go to `instagram_comments`, one document per
  comment by its Graph id. They are read under the posts and reels of the last
  `--media-days` days (90 by default), since an older post still gets comments.

A document already stored with the same text is left alone. A day document
whose stored text has lines the new read lacks (a message since unsent) is
left alone too, so a sync never shrinks one.

The Graph API returns a conversation's whole history, so the initial load is
the same sync over a longer window:

    uv run messaging-sync [--days N] [--media-days N]
    uv run messaging-sync --days 1100 --media-days 1100   # initial load
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from domain.contracts import DataSourceError, EmbeddingError, InstagramComment
from infrastructure.embedding_client import EmbeddingClient
from infrastructure.firestore_client import (
    EMBEDDING_TEXT_FIELD,
    INSTAGRAM_COMMENTS,
    INSTAGRAM_MESSAGES,
    VECTOR_FIELD,
    FirestoreClient,
)
from infrastructure.instagram_meta_client import (
    InstagramMetaClient,
    MediaComment,
    MetaApiError,
)
from routines.vector_indexer.indexer import (
    DM_TIMEZONE,
    IndexDocument,
    message_documents,
)

logger = logging.getLogger(__name__)

DAYS = 21
MEDIA_DAYS = 90
# Comment requests in flight at once.
CONCURRENCY = 5
# Documents embedded and written together.
CHUNK = 100


@dataclass
class SyncSummary:
    written: dict[str, int] = field(default_factory=dict)
    # What could not be read or stored, by collection.
    failed: dict[str, str] = field(default_factory=dict)


def window_start(now: datetime, days: int) -> datetime:
    """Kyiv midnight `days` days before `now`'s Kyiv date, so no day is read in part."""
    day = now.astimezone(DM_TIMEZONE).date() - timedelta(days=days)
    return datetime.combine(day, time(), tzinfo=DM_TIMEZONE).astimezone(UTC)


def comment_document(comment: MediaComment) -> IndexDocument:
    model = InstagramComment(
        sender=comment.username,
        text=comment.text.strip(),
        timestamp=comment.timestamp,
        parent_id=comment.media_id,
    )
    data = model.model_dump(by_alias=True, exclude={"distance"})
    data[EMBEDDING_TEXT_FIELD] = model.text
    return IndexDocument(comment.id, data)


def _grew(stored: str, new: str) -> bool:
    """`new` holds every line of `stored`, and something more."""
    return stored != new and set(stored.splitlines()) <= set(new.splitlines())


async def store_new(
    collection: str,
    docs: Iterable[IndexDocument],
    firestore: FirestoreClient,
    embedder: EmbeddingClient,
) -> int:
    """Embed and write the documents not stored yet, or stored with less text."""
    unique = {d.id: d for d in docs if d.data[EMBEDDING_TEXT_FIELD]}
    stored = await firestore.stored_texts(collection, unique)
    pending = [
        d
        for d in unique.values()
        if d.id not in stored or _grew(stored[d.id], d.data[EMBEDDING_TEXT_FIELD])
    ]
    for start in range(0, len(pending), CHUNK):
        chunk = pending[start : start + CHUNK]
        vectors = await embedder.embed_documents([d.data[EMBEDDING_TEXT_FIELD] for d in chunk])
        await firestore.upsert(
            collection,
            ((d.id, {**d.data, VECTOR_FIELD: v}) for d, v in zip(chunk, vectors, strict=True)),
        )
    return len(pending)


async def sync_messages(meta, firestore, embedder, since: datetime) -> int:
    messages = await meta.list_messages(since)
    docs = message_documents((m.thread, m.sender, m.created, m.text) for m in messages)
    return await store_new(INSTAGRAM_MESSAGES, docs, firestore, embedder)


async def sync_comments(meta, firestore, embedder, since: datetime, media_since: datetime) -> int:
    media = await meta.list_media(since=media_since)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def comments_of(item):
        async with gate:
            return await meta.list_comments(item, since=since)

    found = await asyncio.gather(*map(comments_of, media))
    docs = [comment_document(c) for comments in found for c in comments]
    return await store_new(INSTAGRAM_COMMENTS, docs, firestore, embedder)


async def sync(
    meta: InstagramMetaClient,
    firestore: FirestoreClient,
    embedder: EmbeddingClient,
    days: int = DAYS,
    media_days: int = MEDIA_DAYS,
    now: datetime | None = None,
) -> SyncSummary:
    """Both collections, each on its own: one failing does not stop the other."""
    now = now or datetime.now(UTC)
    since = window_start(now, days)
    parts = {
        INSTAGRAM_MESSAGES: lambda: sync_messages(meta, firestore, embedder, since),
        INSTAGRAM_COMMENTS: lambda: sync_comments(
            meta, firestore, embedder, since, now - timedelta(days=media_days)
        ),
    }
    summary = SyncSummary()
    for collection, run in parts.items():
        try:
            summary.written[collection] = await run()
        except (MetaApiError, DataSourceError, EmbeddingError) as exc:
            logger.error("%s: %s", collection, exc)
            summary.failed[collection] = str(exc)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="messaging-sync", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days", type=int, default=DAYS, help=f"how far back to read (default: {DAYS})"
    )
    parser.add_argument(
        "--media-days", type=int, default=MEDIA_DAYS,
        help=f"read comments under posts and reels this recent (default: {MEDIA_DAYS})",
    )  # fmt: skip
    args = parser.parse_args(argv)

    from infrastructure.env import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    summary = asyncio.run(
        sync(
            InstagramMetaClient(),
            FirestoreClient(),
            EmbeddingClient(),
            days=args.days,
            media_days=args.media_days,
        )
    )
    for collection, written in summary.written.items():
        print(f"{collection}: {written} written")
    for collection, error in summary.failed.items():
        print(f"{collection}: failed: {error}")
    # A failed part fails the job, so the execution shows it.
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
