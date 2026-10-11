"""SearchService.find_similar against the behaviour in specs/search-service.md."""

import pytest

from domain.contracts import EmbeddingError, InvalidArgument, SearchResult
from domain.search_service import DEFAULT_CONTENT_TYPE, THRESHOLD, TOP_K, SearchService
from infrastructure.firestore_client import CONTENT, INSTAGRAM_MESSAGES, PRODUCTS

pytestmark = pytest.mark.unit

VECTOR = [0.1, 0.2]


class _Jev:
    def __init__(self, probabilities=None, error=None):
        self.probabilities = probabilities or {}
        self.error = error
        self.asked = None

    async def choice_probabilities(self, state, instructions, options):
        if self.error:
            raise self.error
        self.asked = (state, instructions, options)
        return {key: self.probabilities.get(key, 0.0) for key in options}


class _Embedder:
    def __init__(self):
        self.queries = []

    async def embed_query(self, text):
        self.queries.append(text)
        return VECTOR


class _Firestore:
    def __init__(self, hits=None):
        self.hits = hits or {}
        self.searched = []
        self.filters = {}

    async def find_nearest(self, collection, vector, limit, filters=None):
        self.searched.append((collection, vector, limit))
        self.filters[collection] = filters
        return self.hits.get(collection, [])


def _service(probabilities=None, hits=None):
    firestore, jev, embedder = _Firestore(hits), _Jev(probabilities), _Embedder()
    return SearchService(firestore, jev, embedder), firestore, jev, embedder


@pytest.mark.parametrize("query", ["", "   ", None])
async def test_empty_query_is_rejected_before_any_call(query):
    service, firestore, jev, embedder = _service()
    with pytest.raises(InvalidArgument):
        await service.find_similar(query)
    assert jev.asked is None and embedder.queries == [] and firestore.searched == []


async def test_only_collections_at_or_above_the_threshold_are_searched():
    service, firestore, jev, _ = _service(
        {PRODUCTS: THRESHOLD, INSTAGRAM_MESSAGES: THRESHOLD - 0.01, CONTENT: 0.41}
    )
    await service.find_similar("шампунь для шпіца")
    assert {c for c, _, _ in firestore.searched} == {PRODUCTS, CONTENT}
    assert all(v == VECTOR and limit == TOP_K[c] for c, v, limit in firestore.searched)
    state, _, options = jev.asked
    assert state == "шампунь для шпіца"
    assert set(options) == {PRODUCTS, INSTAGRAM_MESSAGES, CONTENT}


async def test_unsearched_and_empty_collections_come_back_as_empty_lists():
    service, *_ = _service({PRODUCTS: 0.9})
    result = await service.find_similar("anything")
    assert result == SearchResult()
    assert result.products == [] and result.instagram_messages == [] and result.content == []


async def test_documents_land_in_their_own_field_in_the_order_returned():
    hits = {
        PRODUCTS: [
            {"sku": "A", "name": "first", "price": 10.0, "distance": 0.1},
            {"sku": "B", "name": "second", "price": 20.0, "distance": 0.3},
        ],
        CONTENT: [{"fileName": "dog.jpg", "sizeKb": 12.5, "tags": "шпіц", "distance": 0.2}],
    }
    service, *_ = _service({PRODUCTS: 0.8, CONTENT: 0.7, INSTAGRAM_MESSAGES: 0.1}, hits)
    result = await service.find_similar("шпіц")
    assert [p.sku for p in result.products] == ["A", "B"]
    assert result.products[0].distance == 0.1
    assert result.content[0].file_name == "dog.jpg" and result.content[0].size_kb == 12.5
    assert result.instagram_messages == []


async def test_result_serialises_with_the_contract_field_names():
    hits = {INSTAGRAM_MESSAGES: [{"sender": "x", "text": "привіт", "distance": 0.2}]}
    service, *_ = _service({INSTAGRAM_MESSAGES: 0.95}, hits)
    dumped = (await service.find_similar("привіт")).model_dump(by_alias=True)
    assert set(dumped) == {"products", "instagramMessages", "content"}
    assert "embeddingVector" not in dumped["instagramMessages"][0]


async def test_a_classifier_failure_surfaces_as_embedding_error():
    service = SearchService(_Firestore(), _Jev(error=EmbeddingError("down")), _Embedder())
    with pytest.raises(EmbeddingError):
        await service.find_similar("query")


async def test_each_collection_returns_its_own_number_of_documents():
    service, firestore, *_ = _service({PRODUCTS: 0.34, INSTAGRAM_MESSAGES: 0.33, CONTENT: 0.33})
    await service.find_similar("query")
    assert {c: limit for c, _, limit in firestore.searched} == {
        PRODUCTS: 5,
        INSTAGRAM_MESSAGES: 10,
        CONTENT: 15,
    }


ALL = {PRODUCTS: 0.34, INSTAGRAM_MESSAGES: 0.33, CONTENT: 0.33}


async def test_content_is_filtered_by_type_and_dog_and_the_rest_is_not():
    service, firestore, *_ = _service(ALL)
    await service.find_similar("шпіц", has_dog=True, content_type="креатив")
    assert firestore.filters == {
        PRODUCTS: None,
        INSTAGRAM_MESSAGES: None,
        CONTENT: {"type": "креатив", "hasDog": True},
    }


async def test_without_has_dog_content_is_filtered_by_type_alone():
    service, firestore, *_ = _service(ALL)
    await service.find_similar("шпіц")
    assert firestore.filters[CONTENT] == {"type": DEFAULT_CONTENT_TYPE}


async def test_has_dog_false_asks_for_content_without_a_dog():
    service, firestore, *_ = _service(ALL)
    await service.find_similar("пейзаж", has_dog=False)
    assert firestore.filters[CONTENT]["hasDog"] is False


@pytest.mark.parametrize("content_type", ["", "lifestyle", "скріншот"])
async def test_an_unknown_type_is_rejected_before_any_call(content_type):
    service, firestore, jev, embedder = _service(ALL)
    with pytest.raises(InvalidArgument, match="type"):
        await service.find_similar("q", content_type=content_type)
    assert jev.asked is None and embedder.queries == [] and firestore.searched == []
