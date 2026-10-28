"""search_messaging through a real FastMCP client, with the API mocked."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tools import search_api

SERVER = Path(__file__).resolve().parents[1] / "src" / "mcp-server.py"
RESULT = {"comments": [{"sender": "bob", "text": "Ціна?", "parentId": "m1"}]}


def _server():
    # The file name has a hyphen, so it is loaded by path rather than imported.
    spec = importlib.util.spec_from_file_location("mcp_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


@pytest.fixture
def api(monkeypatch):
    """Replaces the search API; records each request and replays `api.reply`."""
    monkeypatch.setenv("API_URL", "https://hd-api.example.run.app")
    monkeypatch.delenv("API_AUDIENCE", raising=False)
    state = {"requests": [], "reply": httpx.Response(200, json=RESULT)}

    def handler(request):
        state["requests"].append({"url": str(request.url), "body": json.loads(request.content)})
        return state["reply"]

    real = httpx.AsyncClient
    monkeypatch.setattr(
        search_api.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    return state


async def _call(arguments):
    async with Client(_server()) as client:
        return await client.call_tool("search_messaging", arguments)


async def test_the_tool_is_listed_with_the_spec_parameters():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["search_messaging"].input_schema
    assert set(schema["properties"]) == {"from", "to", "messageType", "query"}
    assert not schema.get("required")
    assert "Both" in json.dumps(schema["properties"]["messageType"])


async def test_a_period_reaches_the_api_and_the_answer_comes_back_as_is(api):
    result = await _call(
        {"from": "2026-09-01T00:00:00", "to": " 2026-09-30T23:59:59 ", "messageType": "Comment"}
    )
    (request,) = api["requests"]
    assert request["url"] == "https://hd-api.example.run.app/searchMessaging"
    assert request["body"] == {
        "from": "2026-09-01T00:00:00",
        "to": "2026-09-30T23:59:59",
        "messageType": "Comment",
    }
    assert result.structured_content == RESULT


async def test_a_query_alone_searches_both_by_default(api):
    await _call({"query": " заспокійливі добавки "})
    assert api["requests"][0]["body"] == {"messageType": "Both", "query": "заспокійливі добавки"}


async def test_neither_period_nor_query_is_refused_without_calling_the_api(api):
    with pytest.raises(ToolError, match="period"):
        await _call({"query": "  "})
    assert api["requests"] == []


async def test_api_errors_become_tool_errors(api):
    api["reply"] = httpx.Response(400, json={"detail": "to must not be before from"})
    with pytest.raises(ToolError, match="before from"):
        await _call({"from": "2026-09-30T00:00:00", "to": "2026-09-01T00:00:00"})


async def test_a_query_is_sent_together_with_the_period(api):
    await _call(
        {
            "from": "2026-06-01T00:00:00",
            "to": "2026-06-30T23:59:59",
            "query": "запити щодо замовлень",
        }
    )
    assert api["requests"][0]["body"] == {
        "from": "2026-06-01T00:00:00",
        "to": "2026-06-30T23:59:59",
        "messageType": "Both",
        "query": "запити щодо замовлень",
    }


async def test_the_query_description_teaches_dropping_exclusions():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    query = tools["search_messaging"].input_schema["properties"]["query"]["description"]
    # Exclusions are dropped from the query, and a query is no longer ignored with a period.
    assert "виключаючи" in query and "ignored" not in query
