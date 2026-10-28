"""Finds documents close to a user query. Implements specs/content-search-service.md.

`find_similar`: Jev decides which collections the query is about; only those
are searched, by cosine distance against the query's embedding.
`find_messages`: direct messages and comments, all of a period or the closest
to a query.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infrastructure.embedding_client import EmbeddingClient
from infrastructure.firestore_client import (
    CONTENT,
    INSTAGRAM_COMMENTS,
    INSTAGRAM_MESSAGES,
    PRODUCTS,
    FirestoreClient,
)
from infrastructure.jev_client import JevClient

from .contracts import (
    Content,
    InstagramComment,
    InstagramMessage,
    InvalidArgument,
    MessagingSearchResult,
    Product,
    SearchResult,
)

THRESHOLD = 0.3
# The content types a search can ask for, as the image index writes them.
CONTENT_TYPES = ("лайфстайл", "креатив", "продуктове")
DEFAULT_CONTENT_TYPE = "лайфстайл"
# How many of the closest documents each collection returns.
TOP_K = {PRODUCTS: 5, INSTAGRAM_MESSAGES: 10, CONTENT: 15}

# The query is the state Jev reads; each collection is an option.
JEV_INSTRUCTIONS = "Which collection holds the documents that answer this query?"


COLLECTION_DESCRIPTIONS = {
    PRODUCTS: (
        "The HealthyDoggo catalogue of dog products -- care and hygiene, food, "
        "walking gear, toys and accessories -- with SKU, name, brand, category, "
        "price, description, volume, size and weight."
    ),
    INSTAGRAM_MESSAGES: (
        "Instagram direct messages between HealthyDoggo and its customers, shops "
        "and partners: questions, product consultations, orders, wholesale "
        "enquiries and replies."
    ),
    CONTENT: (
        "HealthyDoggo's library of marketing photos and videos: the dogs and breeds "
        "shown, people, products in frame, scene descriptions, tags, text on the "
        "image and audio transcripts."
    ),
}

_MODELS = {PRODUCTS: Product, INSTAGRAM_MESSAGES: InstagramMessage, CONTENT: Content}
_FIELDS = {PRODUCTS: "products", INSTAGRAM_MESSAGES: "instagram_messages", CONTENT: "content"}

# find_messages: which collections each messageType reads, and the result field
# and model of each.
MESSAGE_TYPES = {
    "Message": (INSTAGRAM_MESSAGES,),
    "Comment": (INSTAGRAM_COMMENTS,),
    "Both": (INSTAGRAM_MESSAGES, INSTAGRAM_COMMENTS),
}
DEFAULT_MESSAGE_TYPE = "Both"
# How many documents are returned per collection: a period's newest, or a
# query's closest. The totals count all of them.
RESULT_LIMIT = 50
# A query's matches: every document at most this cosine distance away, up to
# Firestore's maximum of 1000 per vector search. Messages bunch between 0.25
# and 0.45 from a query; in June 2026 days about ordering still sat at 0.39.
MAX_DISTANCE = 0.4
QUERY_LIMIT = 1000
# Per collection: the result's list field, its total field, and the model.
_MESSAGING = {
    INSTAGRAM_MESSAGES: ("messages", "total_messages_count", InstagramMessage),
    INSTAGRAM_COMMENTS: ("comments", "total_comments_count", InstagramComment),
}


class SearchService:
    def __init__(
        self,
        firestore: FirestoreClient | None = None,
        jev: JevClient | None = None,
        embedder: EmbeddingClient | None = None,
    ) -> None:
        self._firestore = firestore or FirestoreClient()
        self._jev = jev or JevClient()
        self._embedder = embedder or EmbeddingClient()

    async def find_similar(
        self,
        query: str,
        has_dog: bool | None = None,
        content_type: str = DEFAULT_CONTENT_TYPE,
        product_sku: str | None = None,
    ) -> SearchResult:
        """Documents close to `query`.

        `has_dog` and `content_type` narrow the content collection only: to
        files with (True) or without (False) a dog in them -- any, when None --
        and of the one type given. `product_sku` narrows the products to the
        one with that exact SKU, and has products searched even when Jev
        would leave them out. Messages are never filtered.
        """
        if not query or not query.strip():
            raise InvalidArgument("query must not be empty")
        if content_type not in CONTENT_TYPES:
            raise InvalidArgument(
                f"type must be one of {', '.join(CONTENT_TYPES)}, got {content_type!r}"
            )
        filters = {CONTENT: {"type": content_type}}
        if has_dog is not None:
            filters[CONTENT]["hasDog"] = has_dog
        # A blank SKU is no SKU, not a filter that matches nothing.
        if product_sku and product_sku.strip():
            filters[PRODUCTS] = {"sku": product_sku.strip()}

        # Independent calls: classify and embed side by side.
        probabilities, vector = await asyncio.gather(
            self._jev.choice_probabilities(query, JEV_INSTRUCTIONS, COLLECTION_DESCRIPTIONS),
            self._embedder.embed_query(query),
        )
        # A SKU names the product outright, so its collection is searched
        # whatever Jev makes of the wording; Jev still decides the others.
        selected = [
            c
            for c in COLLECTION_DESCRIPTIONS
            if probabilities.get(c, 0.0) >= THRESHOLD or (c == PRODUCTS and PRODUCTS in filters)
        ]
        hits = await asyncio.gather(
            *(self._firestore.find_nearest(c, vector, TOP_K[c], filters.get(c)) for c in selected)
        )

        result = SearchResult()
        for collection, docs in zip(selected, hits, strict=True):
            model = _MODELS[collection]
            setattr(result, _FIELDS[collection], [model.model_validate(d) for d in docs])
        return result

    async def find_messages(
        self,
        query: str | None = None,
        from_: datetime | None = None,
        to: datetime | None = None,
        message_type: str = DEFAULT_MESSAGE_TYPE,
    ) -> MessagingSearchResult:
        """Direct messages and/or comments, by `message_type` (Message, Comment or Both).

        The documents are those of the period -- `from_` and/or `to`,
        inclusive, a naive datetime taken as UTC, `to` now when absent -- that
        are close to `query` (cosine distance at most MAX_DISTANCE); without a
        query, all of the period; without a period, the whole history. A
        period or a query must be given. The RESULT_LIMIT closest (newest,
        without a query) are returned, and the totals count all of them: the
        conversations, each once however many days it ran (a message document
        is a conversation's day, dated by its first message), and the comments.
        """
        if message_type not in MESSAGE_TYPES:
            raise InvalidArgument(
                f"messageType must be one of {', '.join(MESSAGE_TYPES)}, got {message_type!r}"
            )
        collections = MESSAGE_TYPES[message_type]
        since = _utc(from_) if from_ is not None else None
        until = _utc(to) if to is not None else None
        if since is not None and until is None:
            until = datetime.now(UTC)
        if since is not None and until is not None and until < since:
            raise InvalidArgument("to must not be before from")
        query = (query or "").strip()
        if not query and since is None and until is None:
            raise InvalidArgument("give a period (from and/or to) or a query")

        if query:
            vector = await self._embedder.embed_query(query)
            found = await asyncio.gather(
                *(
                    self._firestore.find_nearest(
                        c,
                        vector,
                        QUERY_LIMIT,
                        since=since,
                        until=until,
                        max_distance=MAX_DISTANCE,
                        fields=_stored_fields(_MESSAGING[c][2]),
                    )
                    for c in collections
                )
            )
        else:
            found = await asyncio.gather(
                *(
                    self._firestore.find_in_period(
                        c, since, until, _stored_fields(_MESSAGING[c][2])
                    )
                    for c in collections
                )
            )

        result = MessagingSearchResult()
        for collection, docs in zip(collections, found, strict=True):
            field, total, model = _MESSAGING[collection]
            if collection == INSTAGRAM_MESSAGES:
                # Conversations, not their days: `sender` names the conversation.
                setattr(result, total, len({d.get("sender") for d in docs}))
            else:
                setattr(result, total, len(docs))
            setattr(result, field, [model.model_validate(d) for d in docs[:RESULT_LIMIT]])
        return result


def _utc(moment: datetime) -> datetime:
    """A naive datetime is taken as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _stored_fields(model) -> list[str]:
    """The Firestore names of a model's fields, the distance left out."""
    return [f.alias or name for name, f in model.model_fields.items() if name != "distance"]
