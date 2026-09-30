"""The infrastructure clients: Jev, Gemini embeddings, Firestore."""

import json
from types import SimpleNamespace

import httpx
import pytest

from domain.contracts import DataSourceError, EmbeddingError
from infrastructure import embedding_client, firestore_client
from infrastructure.embedding_client import DIMENSION, EmbeddingClient
from infrastructure.firestore_client import FirestoreClient
from infrastructure.jev_client import MODEL, QUESTION_ID, URL, JevClient

pytestmark = pytest.mark.unit

OPTIONS = {"products": "the catalogue", "content": "photos and videos"}


def _jev(handler, api_key="key"):
    return JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key=api_key)


# --- Jev -----------------------------------------------------------------------


async def test_jev_asks_one_choice_question_and_reads_each_options_probability():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    QUESTION_ID: {
                        "type": "choice",
                        "choice": "products",
                        "probabilities": {"products": 0.88, "content": 0.12},
                        "confidence": 0.81,
                    }
                },
            },
        )

    probabilities = await _jev(handler).choice_probabilities("шампунь", "which?", OPTIONS)

    assert probabilities == {"products": 0.88, "content": 0.12}
    assert seen["url"] == URL and seen["auth"] == "Bearer key"
    assert seen["body"] == {
        "model": MODEL,
        "state": "шампунь",
        "questions": {
            QUESTION_ID: {"type": "choice", "instructions": "which?", "criteria": OPTIONS}
        },
    }


async def test_jev_option_missing_from_the_answer_has_probability_zero():
    answer = {"answers": {QUESTION_ID: {"probabilities": {"products": 1.0}}}}
    probabilities = await _jev(lambda r: httpx.Response(200, json=answer)).choice_probabilities(
        "q", "which?", OPTIONS
    )
    assert probabilities == {"products": 1.0, "content": 0.0}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "bad key"}),
        httpx.Response(529, json={}),
        httpx.Response(200, json={"answers": {QUESTION_ID: {"choice": "products"}}}),
    ],
)
async def test_jev_failures_raise_embedding_error(response):
    with pytest.raises(EmbeddingError):
        await _jev(lambda request: response).choice_probabilities("q", "which?", OPTIONS)


async def test_jev_without_a_key_fails_before_calling(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def handler(request):
        raise AssertionError("should not be called")

    with pytest.raises(EmbeddingError, match="TYPESAFE_API_KEY"):
        await _jev(handler, api_key="").choice_probabilities("q", "which?", OPTIONS)


# --- Embeddings ------------------------------------------------------------------


class _Genai:
    def __init__(self, dimension=DIMENSION, error=None):
        self.calls = []
        self.dimension = dimension
        self.error = error
        self.aio = SimpleNamespace(models=self)

    async def embed_content(self, *, model, contents, config):
        if self.error:
            raise self.error
        texts = [c.parts[0].text for c in contents]
        self.calls.append((model, texts, config.output_dimensionality))
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[float(i)] * self.dimension) for i in range(len(texts))
            ]
        )


async def test_query_and_documents_carry_different_task_prefixes():
    genai = _Genai()
    client = EmbeddingClient(client=genai)
    await client.embed_query("шампунь")
    await client.embed_documents(["товар"])
    (_, query, dim), (_, docs, _) = genai.calls
    assert query == ["task: search result | query: шампунь"]
    assert docs == ["title: none | text: товар"]
    assert dim == DIMENSION


async def test_documents_are_embedded_in_batches_and_come_back_in_order(monkeypatch):
    monkeypatch.setattr(embedding_client, "BATCH_SIZE", 2)
    genai = _Genai()
    vectors = await EmbeddingClient(client=genai).embed_documents(["a", "b", "c"])
    assert [len(texts) for _, texts, _ in genai.calls] == [2, 1]
    assert [v[0] for v in vectors] == [0.0, 1.0, 0.0]


@pytest.mark.parametrize("genai", [_Genai(error=RuntimeError("quota")), _Genai(dimension=3072)])
async def test_embedding_failures_raise_embedding_error(genai):
    with pytest.raises(EmbeddingError):
        await EmbeddingClient(client=genai).embed_query("q")


# --- Firestore ---------------------------------------------------------------------


class _Snapshot:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _VectorQuery:
    def __init__(self, docs, error=None):
        self.docs, self.error = docs, error

    async def stream(self):
        if self.error:
            raise self.error
        for d in self.docs:
            yield _Snapshot(d)


class _Collection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def find_nearest(self, **kwargs):
        self.store.queries.append((self.name, kwargs))
        return _VectorQuery(self.store.results, self.store.error)

    def document(self, doc_id):
        return (self.name, doc_id)


class _Batch:
    def __init__(self, store):
        self.store, self.writes = store, []

    def set(self, ref, data):
        self.writes.append((ref, data))

    async def commit(self):
        self.store.commits.append(self.writes)


class _Firestore:
    def __init__(self, results=(), error=None):
        self.results, self.error = list(results), error
        self.queries, self.commits = [], []

    def collection(self, name):
        return _Collection(self, name)

    def batch(self):
        return _Batch(self)


async def test_find_nearest_uses_cosine_and_drops_the_embedding_fields():
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

    fake = _Firestore(
        [
            {"sku": "B", "distance": 0.4, "embeddingVector": [1], "embeddingText": "t"},
            {"sku": "A", "distance": 0.1, "embeddingVector": [1], "embeddingText": "t"},
        ]
    )
    docs = await FirestoreClient(client=fake).find_nearest("products", [0.5], 5)

    assert docs == [{"sku": "A", "distance": 0.1}, {"sku": "B", "distance": 0.4}]
    name, kwargs = fake.queries[0]
    assert name == "products" and kwargs["limit"] == 5
    assert kwargs["distance_measure"] == DistanceMeasure.COSINE
    assert kwargs["distance_result_field"] == "distance"
    assert kwargs["vector_field"] == "embeddingVector"


async def test_a_firestore_failure_raises_data_source_error():
    fake = _Firestore(error=RuntimeError("permission denied"))
    with pytest.raises(DataSourceError):
        await FirestoreClient(client=fake).find_nearest("products", [0.5], 5)


async def test_upsert_stores_the_vector_as_a_firestore_vector_in_batches(monkeypatch):
    from google.cloud.firestore_v1.vector import Vector

    monkeypatch.setattr(firestore_client, "WRITE_BATCH", 2)
    fake = _Firestore()
    docs = [(str(i), {"sku": str(i), "embeddingVector": [0.1, 0.2]}) for i in range(3)]
    await FirestoreClient(client=fake).upsert("products", docs)

    assert [len(c) for c in fake.commits] == [2, 1]
    ref, data = fake.commits[0][0]
    assert ref == ("products", "0")
    assert isinstance(data["embeddingVector"], Vector)
