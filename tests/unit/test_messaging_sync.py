"""messaging-sync: the Graph API's comments and messages, and storing what is new."""

from datetime import UTC, datetime

import httpx
import pytest

from infrastructure.firestore_client import (
    EMBEDDING_TEXT_FIELD,
    INSTAGRAM_COMMENTS,
    INSTAGRAM_MESSAGES,
    VECTOR_FIELD,
)
from infrastructure.instagram_meta_client import (
    DirectMessage,
    InstagramMedia,
    InstagramMetaClient,
    MediaComment,
    MetaApiError,
)
from routines.messaging_sync import sync as messaging_sync
from routines.messaging_sync.sync import comment_document, sync, window_start
from routines.vector_indexer.indexer import message_documents

pytestmark = pytest.mark.unit

BASE = "https://graph.facebook.com/v23.0"
SINCE = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
POST = InstagramMedia("m1", "IMAGE", "FEED", SINCE, permalink="https://ig/p/1")


def _client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return InstagramMetaClient(
        http,
        access_token="user-token",
        instagram_user_id="shop-ig",
        facebook_page_id="page",
        graph_version="v23.0",
    )


# --- The Graph API --------------------------------------------------------------


async def test_comments_and_their_replies_are_read_and_old_ones_dropped():
    def handler(request):
        assert request.url.path == "/v23.0/m1/comments"
        assert "replies.limit(50)" in request.url.params["fields"]
        return httpx.Response(200, json={"data": [
            {"id": "c1", "text": "Скільки коштує?", "username": "anna", "timestamp": "2026-10-20T10:00:00+0000",
             "replies": {"data": [{"id": "r1", "text": "349 грн", "username": "healthydoggo", "timestamp": "2026-10-20T11:00:00+0000"}]}},
            {"id": "c0", "text": "old", "username": "bob", "timestamp": "2026-09-01T10:00:00+0000"},
        ]})  # fmt: skip

    comments = await _client(handler).list_comments(POST, since=SINCE)

    assert [(c.id, c.parent_id, c.permalink) for c in comments] == [
        ("c1", "", "https://ig/p/1"),
        ("r1", "c1", "https://ig/p/1"),
    ]


async def test_messages_are_read_with_the_page_token_and_stop_at_the_window():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers["authorization"]))
        path = request.url.path
        if path == "/v23.0/page":
            return httpx.Response(200, json={"access_token": "page-token"})
        if path == "/v23.0/page/conversations":
            assert request.url.params["platform"] == "instagram"
            return httpx.Response(200, json={"data": [
                {"id": "t1", "updated_time": "2026-10-20T10:00:00+0000",
                 "participants": {"data": [{"id": "shop-ig", "username": "healthydoggo"}, {"id": "u1", "username": "anna"}]}},
                {"id": "t0", "updated_time": "2026-09-01T10:00:00+0000", "participants": {"data": []}},
            ]})  # fmt: skip
        if path == "/v23.0/t1/messages":
            return httpx.Response(200, json={"data": [
                {"id": "x2", "created_time": "2026-10-20T10:00:00+0000", "from": {"username": "healthydoggo"}, "message": "Добрий день!"},
                {"id": "x1", "created_time": "2026-10-20T09:00:00+0000", "from": {"username": "anna", "id": "u1"}, "message": "Є шампунь?"},
                {"id": "x0", "created_time": "2026-09-30T09:00:00+0000", "from": {"username": "anna"}, "message": "old"},
            ]})  # fmt: skip
        pytest.fail(f"unexpected {path}")

    messages = await _client(handler).list_messages(SINCE)

    assert [(m.id, m.thread, m.sender) for m in messages] == [
        ("x2", "anna", "healthydoggo"),
        ("x1", "anna", "anna"),
    ]
    assert seen[0] == ("/v23.0/page", "Bearer user-token")
    assert all(auth == "Bearer page-token" for _, auth in seen[1:])
    assert ("/v23.0/t0/messages", "Bearer page-token") not in seen


async def test_a_page_graph_finds_too_big_is_asked_for_again_smaller():
    limits = []

    def handler(request):
        limits.append(request.url.params["limit"])
        if request.url.params.get("after") is None:
            return httpx.Response(200, json={
                "data": [{"id": "c1", "text": "a", "timestamp": "2026-10-20T10:00:00+0000"}],
                "paging": {"next": f"{BASE}/m1/comments?limit=50&after=x"},
            })  # fmt: skip
        if request.url.params["limit"] == "50":
            return httpx.Response(500, json={"error": {"code": 1, "message":
                "Please reduce the amount of data you're asking for, then retry your request"}})  # fmt: skip
        return httpx.Response(200, json={"data": [
            {"id": "c2", "text": "b", "timestamp": "2026-10-20T11:00:00+0000"}]})  # fmt: skip

    comments = await _client(handler).list_comments(POST, since=SINCE)

    assert [c.id for c in comments] == ["c1", "c2"]
    assert limits == ["50", "50", "25"]


async def test_messages_need_the_facebook_page(monkeypatch):
    monkeypatch.delenv("FACEBOOK_PAGE_ID", raising=False)
    client = InstagramMetaClient(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("sent"))),
        access_token="t",
        instagram_user_id="shop-ig",
    )
    with pytest.raises(MetaApiError, match="FACEBOOK_PAGE_ID"):
        await client.list_messages(SINCE)


# --- Sync ------------------------------------------------------------------------


def test_the_window_starts_at_a_kyiv_midnight():
    # 25 Oct 12:00 UTC is 25 Oct in Kyiv; 21 days before is 4 Oct, 00:00 Kyiv (UTC+3).
    assert window_start(NOW, 21) == datetime(2026, 10, 3, 21, tzinfo=UTC)


def _message(text, sender="anna", at=datetime(2026, 10, 20, 9, tzinfo=UTC), id_=None):
    return DirectMessage(id_ or text, "anna", sender, text, at)


def _comment(id_, text="Класний шампунь"):
    return MediaComment(
        id_, "m1", "anna", text, datetime(2026, 10, 20, tzinfo=UTC), "https://ig/p/1"
    )


class _Meta:
    def __init__(self, messages=(), comments=(), error=None):
        self.messages, self.comments, self.error = list(messages), list(comments), error
        self.calls = {}

    async def list_messages(self, since):
        self.calls["messages"] = since
        if self.error:
            raise self.error
        return self.messages

    async def list_media(self, since=None):
        self.calls["media"] = since
        return [POST]

    async def list_comments(self, media, since=None):
        self.calls["comments"] = since
        return self.comments


class _Firestore:
    def __init__(self, stored=None):
        self.stored = {c: dict(docs) for c, docs in (stored or {}).items()}
        self.written = {}

    async def stored_texts(self, collection, ids):
        docs = self.stored.get(collection, {})
        return {i: docs[i] for i in ids if i in docs}

    async def upsert(self, collection, documents):
        for doc_id, data in documents:
            self.written.setdefault(collection, {})[doc_id] = data


class _Embedder:
    def __init__(self):
        self.texts = []

    async def embed_documents(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 3 for _ in texts]


async def test_a_day_of_messages_becomes_one_embedded_document_and_comments_their_own():
    meta = _Meta(
        messages=[_message("Є шампунь?"), _message("А для цуценят?", id_="x2")],
        comments=[_comment("c1"), _comment("c2", text="  ")],
    )
    firestore, embedder = _Firestore(), _Embedder()

    summary = await sync(meta, firestore, embedder, now=NOW)

    assert summary.written == {INSTAGRAM_MESSAGES: 1, INSTAGRAM_COMMENTS: 1}
    (day,) = firestore.written[INSTAGRAM_MESSAGES].values()
    assert day["text"] == "anna: Є шампунь?\nanna: А для цуценят?" and day["sender"] == "anna"
    assert day[VECTOR_FIELD] == [0.1] * 3
    comment = firestore.written[INSTAGRAM_COMMENTS]["c1"]
    assert (comment["sender"], comment["text"], comment["parentId"]) == (
        "anna",
        "Класний шампунь",
        "m1",
    )
    assert comment[EMBEDDING_TEXT_FIELD] == "Класний шампунь"
    # Messages from the Kyiv midnight; comments under media of the last 90 days.
    assert meta.calls["messages"] == meta.calls["comments"] == window_start(NOW, 21)
    assert meta.calls["media"] == datetime(2026, 7, 27, 12, tzinfo=UTC)


async def test_only_new_or_grown_documents_are_written():
    old_day = message_documents(
        [("anna", "anna", datetime(2026, 10, 19, 9, tzinfo=UTC), "Привіт")]
    )[0]
    grown = message_documents(
        [
            ("anna", "anna", datetime(2026, 10, 20, 9, tzinfo=UTC), t)
            for t in ("Є шампунь?", "Дякую")
        ]
    )[0]
    shrunk = message_documents([("bob", "bob", datetime(2026, 10, 20, 9, tzinfo=UTC), "Так")])[0]
    stored = {
        INSTAGRAM_MESSAGES: {
            old_day.id: "anna: Привіт",  # unchanged
            grown.id: "anna: Є шампунь?",  # gained a message
            shrunk.id: "bob: Так\nbob: А ще?",  # the API returned less than is stored
        },
        INSTAGRAM_COMMENTS: {"c1": "Класний шампунь"},
    }
    meta = _Meta(
        messages=[
            _message("Привіт", at=datetime(2026, 10, 19, 9, tzinfo=UTC)),
            _message("Є шампунь?"),
            _message("Дякую", id_="x3"),
            DirectMessage("y1", "bob", "bob", "Так", datetime(2026, 10, 20, 9, tzinfo=UTC)),
        ],
        comments=[_comment("c1"), _comment("c2", text="Де купити?")],
    )
    firestore, embedder = _Firestore(stored), _Embedder()

    summary = await sync(meta, firestore, embedder, now=NOW)

    assert set(firestore.written[INSTAGRAM_MESSAGES]) == {grown.id}
    assert set(firestore.written[INSTAGRAM_COMMENTS]) == {"c2"}
    assert embedder.texts == ["anna: Є шампунь?\nanna: Дякую", "Де купити?"]
    assert summary.written == {INSTAGRAM_MESSAGES: 1, INSTAGRAM_COMMENTS: 1}


async def test_messages_failing_do_not_stop_comments():
    meta = _Meta(comments=[_comment("c1")], error=MetaApiError("(#10) no permission", code=10))
    firestore = _Firestore()

    summary = await sync(meta, firestore, _Embedder(), now=NOW)

    assert summary.failed == {INSTAGRAM_MESSAGES: "(#10) no permission"}
    assert set(firestore.written[INSTAGRAM_COMMENTS]) == {"c1"}


def test_a_failed_part_fails_the_job(monkeypatch, capsys):
    async def failing(*args, **kwargs):
        return messaging_sync.SyncSummary(
            written={INSTAGRAM_COMMENTS: 2}, failed={INSTAGRAM_MESSAGES: "no permission"}
        )

    monkeypatch.setattr(messaging_sync, "sync", failing)
    # main() reads .env; keep it out of the environment of later tests.
    monkeypatch.setattr("infrastructure.env.load_dotenv", lambda: None)
    for cls in ("InstagramMetaClient", "FirestoreClient", "EmbeddingClient"):
        monkeypatch.setattr(messaging_sync, cls, lambda: None)

    assert messaging_sync.main([]) == 1
    out = capsys.readouterr().out
    assert "instagram_comments: 2 written" in out
    assert "instagram_messages: failed: no permission" in out


def test_a_comment_document_has_the_spec_fields():
    doc = comment_document(_comment("c9"))
    assert doc.id == "c9"
    assert set(doc.data) == {"sender", "text", "timestamp", "parentId", EMBEDDING_TEXT_FIELD}
