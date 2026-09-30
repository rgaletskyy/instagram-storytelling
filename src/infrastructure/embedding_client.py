"""Text embeddings from gemini-embedding-2.

The model takes no task_type. Queries and documents are told apart by a prefix
in the text itself, and the two must differ: a query embedded like a document
lands next to other queries, not next to the documents that answer it.
"""

from __future__ import annotations

import asyncio
import os

from domain.contracts import EmbeddingError

MODEL = "gemini-embedding-2"
# Firestore indexes vectors of at most 2048 dimensions, so the model's native
# 3072 could be stored but never searched. 1536 is one of the sizes Google
# recommends; the model normalises a truncated vector itself.
DIMENSION = 1536
# Inputs per request. Each is wrapped in its own Content: passed as bare
# strings, several inputs come back as one aggregated embedding.
BATCH_SIZE = 50

_QUERY_PREFIX = "task: search result | query: "
_DOCUMENT_PREFIX = "title: none | text: "


class EmbeddingClient:
    def __init__(self, client=None, api_key: str | None = None) -> None:
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
        # Held for the client's lifetime: an unreferenced genai client is
        # garbage-collected and closed mid-request.
        self._client = client

    async def embed_query(self, text: str) -> list[float]:
        (vector,) = await self._embed([_QUERY_PREFIX + text])
        return vector

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        batches = [
            [_DOCUMENT_PREFIX + t for t in texts[i : i + BATCH_SIZE]]
            for i in range(0, len(texts), BATCH_SIZE)
        ]
        results = await asyncio.gather(*(self._embed(b) for b in batches))
        return [vector for batch in results for vector in batch]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        try:
            response = await self._client.aio.models.embed_content(
                model=MODEL,
                contents=[types.Content(parts=[types.Part(text=t)]) for t in texts],
                config=types.EmbedContentConfig(output_dimensionality=DIMENSION),
            )
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"{MODEL} could not embed: {exc}") from exc
        vectors = [list(e.values or []) for e in response.embeddings or []]
        if len(vectors) != len(texts) or any(len(v) != DIMENSION for v in vectors):
            raise EmbeddingError(
                f"{MODEL} returned {len(vectors)} embeddings for {len(texts)} inputs, "
                f"expected {DIMENSION} dimensions each"
            )
        return vectors
