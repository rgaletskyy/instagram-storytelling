"""SearchService against the behaviour in specs/content-search-service.md."""

from datetime import UTC, datetime, timedelta

import pytest

from domain.content_search_service import (
    DEFAULT_CONTENT_TYPE,
    MESSAGING_TOP_K,
    PERIOD_LIMIT,
    THRESHOLD,
    TOP_K,
    SearchService,
)
from domain.contracts import EmbeddingError, InvalidArgument, MessagingSearchResult, SearchResult
from infrastructure.firestore_client import (
    CONTENT,
    INSTAGRAM_COMMENTS,
    INSTAGRAM_MESSAGES,
    PRODUCTS,
)

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

    async def find_in_period(self, collection, since, until, fields):
        self.searched.append((collection, since, until))
        self.filters[collection] = fields
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


async def test_a_sku_narrows_products_and_nothing_else():
    service, firestore, *_ = _service(ALL)
    await service.find_similar("бальзам", product_sku=" ND-PAWS-01 ")
    assert firestore.filters[PRODUCTS] == {"sku": "ND-PAWS-01"}
    assert firestore.filters[INSTAGRAM_MESSAGES] is None
    assert firestore.filters[CONTENT] == {"type": DEFAULT_CONTENT_TYPE}


@pytest.mark.parametrize("sku", [None, "", "   "])
async def test_no_sku_leaves_products_unfiltered(sku):
    service, firestore, *_ = _service(ALL)
    await service.find_similar("бальзам", product_sku=sku)
    assert firestore.filters[PRODUCTS] is None


async def test_a_sku_has_products_searched_even_when_jev_leaves_them_out():
    service, firestore, *_ = _service({PRODUCTS: 0.05, CONTENT: 0.95})
    await service.find_similar("фото для сторіз", product_sku="ND-PAWS-01")
    assert {c for c, _, _ in firestore.searched} == {PRODUCTS, CONTENT}
    assert firestore.filters[PRODUCTS] == {"sku": "ND-PAWS-01"}


async def test_without_a_sku_jev_still_decides_on_products():
    service, firestore, *_ = _service({PRODUCTS: 0.05, CONTENT: 0.95})
    await service.find_similar("фото для сторіз", product_sku="  ")
    assert {c for c, _, _ in firestore.searched} == {CONTENT}


# --- find_messages ---------------------------------------------------------------

DAY = {"sender": "anna", "text": "anna: Є шампунь?\nhealthydoggo.ua: Так", "timestamp": datetime(2026, 6, 3, tzinfo=UTC)}  # fmt: skip
COMMENT = {"sender": "bob", "text": "Ціна?", "timestamp": datetime(2026, 6, 4, tzinfo=UTC), "parentId": "m1"}  # fmt: skip


async def test_a_period_returns_everything_in_it_from_both_collections_without_embedding():
    service, firestore, _, embedder = _service(
        hits={INSTAGRAM_MESSAGES: [DAY], INSTAGRAM_COMMENTS: [COMMENT]}
    )

    result = await service.find_messages(
        "ignored", from_=datetime(2026, 6, 1), to=datetime(2026, 6, 30, 23, 59, 59)
    )

    assert [m.text for m in result.messages] == [DAY["text"]]
    assert [(c.sender, c.parent_id) for c in result.comments] == [("bob", "m1")]
    # Naive datetimes are UTC; the query is not used with a period.
    assert firestore.searched == [
        (INSTAGRAM_MESSAGES, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)),
        (INSTAGRAM_COMMENTS, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)),
    ]  # fmt: skip
    assert embedder.queries == []
    # Only the stored fields are read, never the vectors.
    assert firestore.filters[INSTAGRAM_COMMENTS] == ["sender", "text", "timestamp", "parentId"]


async def test_a_period_with_only_from_runs_to_now_and_with_only_to_from_the_start():
    service, firestore, *_ = _service()
    before = datetime.now(UTC)

    await service.find_messages(from_=datetime(2026, 6, 1, tzinfo=UTC), message_type="Message")
    await service.find_messages(to=datetime(2026, 6, 30, tzinfo=UTC), message_type="Comment")

    (c1, since1, until1), (c2, since2, until2) = firestore.searched
    assert (c1, since1) == (INSTAGRAM_MESSAGES, datetime(2026, 6, 1, tzinfo=UTC))
    assert before <= until1 <= datetime.now(UTC) + timedelta(seconds=1)
    assert (c2, since2, until2) == (INSTAGRAM_COMMENTS, None, datetime(2026, 6, 30, tzinfo=UTC))


async def test_without_a_period_the_closest_to_the_query_are_returned():
    service, firestore, _, embedder = _service(
        hits={INSTAGRAM_COMMENTS: [{**COMMENT, "distance": 0.2}]}
    )

    result = await service.find_messages("ціна шампуню", message_type="Comment")

    assert embedder.queries == ["ціна шампуню"]
    assert firestore.searched == [(INSTAGRAM_COMMENTS, VECTOR, MESSAGING_TOP_K)]
    assert result.messages == [] and result.comments[0].distance == 0.2
    # Totals belong to a period only.
    assert result.total_messages_count is None and result.total_comments_count is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": "  "}, "query"),
        ({}, "query"),
        ({"query": "x", "message_type": "DM"}, "messageType"),
        ({"from_": datetime(2026, 6, 2), "to": datetime(2026, 6, 1)}, "before"),
    ],
)
async def test_bad_messaging_arguments_are_rejected_before_any_call(kwargs, message):
    service, firestore, _, embedder = _service()
    with pytest.raises(InvalidArgument, match=message):
        await service.find_messages(**kwargs)
    assert firestore.searched == [] and embedder.queries == []


async def test_an_empty_messaging_result_has_empty_lists():
    service, *_ = _service()
    assert await service.find_messages("x") == MessagingSearchResult()


async def test_a_period_returns_the_newest_fifty_and_counts_all_of_it():
    # 60 conversation-days of 20 customers, three days each.
    days = [{**DAY, "sender": f"customer{i % 20}"} for i in range(60)]
    comments = [COMMENT] * 70
    service, *_ = _service(hits={INSTAGRAM_MESSAGES: days, INSTAGRAM_COMMENTS: comments})

    result = await service.find_messages(from_=datetime(2026, 6, 1))

    assert len(result.messages) == len(result.comments) == PERIOD_LIMIT == 50
    # Each conversation once, however many of its days fall in the period.
    assert result.total_messages_count == 20
    assert result.total_comments_count == 70


async def test_a_collection_not_read_has_no_total():
    service, *_ = _service()

    result = await service.find_messages(from_=datetime(2026, 6, 1), message_type="Comment")

    assert result.total_comments_count == 0 and result.total_messages_count is None
