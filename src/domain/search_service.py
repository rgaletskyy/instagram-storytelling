"""Finds documents close to a user query. Implements specs/search-service.md.

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
TOP_K = 5

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

    async def find_similar(self, query: str) -> SearchResult:
        if not query or not query.strip():
            raise InvalidArgument("query must not be empty")

        # Independent calls: classify and embed side by side.
        probabilities, vector = await asyncio.gather(
            self._jev.choice_probabilities(query, JEV_INSTRUCTIONS, COLLECTION_DESCRIPTIONS),
            self._embedder.embed_query(query),
        )
        selected = [c for c in COLLECTION_DESCRIPTIONS if probabilities.get(c, 0.0) >= THRESHOLD]
        hits = await asyncio.gather(
            *(self._firestore.find_nearest(c, vector, TOP_K) for c in selected)
        )

        result = SearchResult()
        for collection, docs in zip(selected, hits, strict=True):
            model = _MODELS[collection]
            setattr(result, _FIELDS[collection], [model.model_validate(d) for d in docs])
        return result
