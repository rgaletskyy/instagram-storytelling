"""search_knowledge_base through a real FastMCP client, with the API mocked."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tools import search_knowledge_base as tool

SERVER = Path(__file__).resolve().parents[1] / "src" / "mcp-server.py"
RESULT = {"products": [{"sku": "ND-PAWS-01"}], "instagramMessages": [], "content": []}


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
        state["requests"].append(
            {
                "url": str(request.url),
                "headers": request.headers,
                "body": json.loads(request.content),
            }
        )
        return state["reply"]

    real = httpx.AsyncClient
    monkeypatch.setattr(
        tool.search_api.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    return state


async def _call(arguments):
    async with Client(_server()) as client:
        return await client.call_tool("search_knowledge_base", arguments)


async def test_the_tool_is_listed_with_the_spec_parameters():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    listed = tools["search_knowledge_base"]
    props = listed.input_schema["properties"]
    assert set(props) == {"query", "productSku", "hasDog", "contentType"}
    assert listed.input_schema["required"] == ["query"]
    assert "Leave empty" in json.dumps(props["contentType"], ensure_ascii=False)
    assert "лайфстайл" in json.dumps(props["contentType"], ensure_ascii=False)


async def test_all_parameters_reach_the_api_under_its_names(api):
    result = await _call(
        {
            "query": "бальзам для лап",
            "productSku": " ND-PAWS-01 ",
            "hasDog": False,
            "contentType": "креатив",
        }
    )
    (request,) = api["requests"]
    assert request["url"] == "https://hd-api.example.run.app/searchcontent"
    assert request["body"] == {
        "query": "бальзам для лап",
        "productSku": "ND-PAWS-01",
        "hasDog": False,
        "type": "креатив",
    }
    assert result.structured_content == RESULT


async def test_parameters_left_out_are_not_sent(api):
    await _call({"query": "бальзам"})
    assert api["requests"][0]["body"] == {"query": "бальзам"}


async def test_without_an_audience_no_service_token_is_sent(api):
    await _call({"query": "бальзам"})
    assert "authorization" not in api["requests"][0]["headers"]


async def test_with_an_audience_the_service_token_is_sent(api, monkeypatch):
    monkeypatch.setenv("API_AUDIENCE", "https://hd-api.example.run.app")
    monkeypatch.setattr(tool.search_api, "_service_token", lambda audience: f"token-for-{audience}")
    await _call({"query": "бальзам"})
    assert api["requests"][0]["headers"]["authorization"] == (
        "Bearer token-for-https://hd-api.example.run.app"
    )


async def test_an_unknown_content_type_is_rejected_before_calling(api):
    with pytest.raises(ToolError):
        await _call({"query": "бальзам", "contentType": "lifestyle"})
    assert api["requests"] == []


async def test_an_api_error_becomes_a_tool_error_with_its_detail(api):
    api["reply"] = httpx.Response(403, json={"detail": "hd-mcp@x may not call without a user"})
    with pytest.raises(ToolError, match="403.*may not call without a user"):
        await _call({"query": "бальзам"})


async def test_the_search_is_logged_to_stderr_never_stdout(api, capsys):
    await _call({"query": "бальзам", "hasDog": True})
    captured = capsys.readouterr()
    assert "search_knowledge_base" not in captured.out
    logged = json.loads(captured.err.strip().splitlines()[-1])
    assert logged["message"] == "search_knowledge_base" and logged["hasDog"] is True
