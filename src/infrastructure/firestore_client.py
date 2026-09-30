"""The `healthydoggo` Firestore database and its three collections.

Each collection needs a vector index on `embeddingVector` before it can be
searched; see "Product search (RAG)" in README.md for the gcloud command.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from domain.contracts import DataSourceError

DATABASE = "healthydoggo"
PRODUCTS = "products"
INSTAGRAM_MESSAGES = "instagram_messages"
CONTENT = "content"
COLLECTIONS = (PRODUCTS, INSTAGRAM_MESSAGES, CONTENT)

EMBEDDING_TEXT_FIELD = "embeddingText"
VECTOR_FIELD = "embeddingVector"
DISTANCE_FIELD = "distance"
# Firestore commits at most 500 writes at once; a document carries a 1536-float
# vector, so a smaller batch also keeps each request well under its size limit.
WRITE_BATCH = 100


class FirestoreClient:
    def __init__(self, client=None, project: str | None = None) -> None:
        if client is None:
            from google.cloud import firestore

            # Credentials come from Application Default Credentials.
            client = firestore.AsyncClient(
                project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"), database=DATABASE
            )
        self._client = client

    async def find_nearest(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        """The `limit` closest documents by cosine distance, closest first.

        Each carries its distance under `distance`; the embedding fields are dropped.
        """
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        query = self._client.collection(collection).find_nearest(
            vector_field=VECTOR_FIELD,
            query_vector=Vector(vector),
            limit=limit,
            distance_measure=DistanceMeasure.COSINE,
            distance_result_field=DISTANCE_FIELD,
        )
        try:
            docs = [snapshot.to_dict() async for snapshot in query.stream()]
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError(f"Firestore search on {collection} failed: {exc}") from exc
        for doc in docs:
            doc.pop(VECTOR_FIELD, None)
            doc.pop(EMBEDDING_TEXT_FIELD, None)
        # The query already returns them closest first; sorting again keeps
        # that a guarantee of this method rather than of the backend.
        return sorted(docs, key=lambda d: d.get(DISTANCE_FIELD, float("inf")))

    async def existing_ids(self, collection: str) -> set[str]:
        try:
            return {
                ref.id
                async for ref in self._client.collection(collection).list_documents(page_size=1000)
            }
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError(f"Firestore could not list {collection}: {exc}") from exc

    async def upsert(self, collection: str, documents: Iterable[tuple[str, dict]]) -> None:
        """Write documents by id. A `embeddingVector` list is stored as a Firestore vector."""
        from google.cloud.firestore_v1.vector import Vector

        docs = list(documents)
        col = self._client.collection(collection)
        try:
            for start in range(0, len(docs), WRITE_BATCH):
                batch = self._client.batch()
                for doc_id, data in docs[start : start + WRITE_BATCH]:
                    data = dict(data)
                    if VECTOR_FIELD in data:
                        data[VECTOR_FIELD] = Vector(data[VECTOR_FIELD])
                    batch.set(col.document(doc_id), data)
                await batch.commit()
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError(f"Firestore could not write to {collection}: {exc}") from exc
