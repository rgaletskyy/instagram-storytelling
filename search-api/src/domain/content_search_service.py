"""Finds documents close to a user query. Implements specs/content-search-service.md.

Jev decides which collections the query is about; only those are searched, by
cosine distance against the query's embedding.
"""

from __future__ import annotations

import asyncio

from infrastructure.embedding_client import EmbeddingClient
from infrastructure.firestore_client import (
    CONTENT,
    INSTAGRAM_MESSAGES,
    PRODUCTS,
    FirestoreClient,
)
from infrastructure.jev_client import JevClient

from .contracts import Content, InstagramMessage, InvalidArgument, Product, SearchResult

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
