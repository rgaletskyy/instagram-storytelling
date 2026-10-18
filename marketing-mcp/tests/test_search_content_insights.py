"""search_content_insights through a real FastMCP client, with the API mocked."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tools import search_api

SERVER = Path(__file__).resolve().parents[1] / "src" / "mcp-server.py"
RESULT = {
    "items": [{"id": "1", "permaLink": "https://ig/p/1", "likes": 706, "saved": 224}],
    "errorCode": None,
    "errorMessage": None,
}


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
        return await client.call_tool("search_content_insights", arguments)


async def test_the_tool_is_listed_with_the_spec_parameters():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["search_content_insights"].input_schema
    assert set(schema["properties"]) == {
        "from", "to", "mediaProductType", "mediaType", "sortBy", "topN",
    }  # fmt: skip
    assert schema["required"] == ["from"]
    props = json.dumps(schema["properties"])
    assert "CAROUSEL_ALBUM" in props and "totalInteractions" in props and "today" in props


async def test_all_parameters_reach_the_api_under_its_names(api):
    result = await _call(
        {
            "from": "2026-05-01T00:00:00",
            "to": " 2026-05-31T23:59:59 ",
            "mediaProductType": "FEED",
            "mediaType": "CAROUSEL_ALBUM",
            "sortBy": "likes,saved",
            "topN": 5,
        }
    )
    (request,) = api["requests"]
    assert request["url"] == "https://hd-api.example.run.app/searchContentInsights"
    assert request["body"] == {
        "from": "2026-05-01T00:00:00",
        "to": "2026-05-31T23:59:59",
        "mediaProductType": "FEED",
        "mediaType": "CAROUSEL_ALBUM",
        "sortBy": "likes,saved",
        "topN": 5,
    }
    assert result.structured_content == RESULT


async def test_parameters_left_out_are_not_sent(api):
    await _call({"from": "2026-05-01T00:00:00", "to": "", "sortBy": " "})
    assert api["requests"][0]["body"] == {"from": "2026-05-01T00:00:00"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"from": "2026-05-01", "mediaProductType": "POST"},
        {"from": "2026-05-01", "mediaType": "PHOTO"},
        {"from": "2026-05-01", "topN": 0},
        {"from": " "},
        {},
    ],
)
async def test_invalid_arguments_are_rejected_before_calling(api, arguments):
    with pytest.raises(ToolError):
        await _call(arguments)
    assert api["requests"] == []


async def test_an_api_refusal_becomes_a_tool_error_with_its_detail(api):
    api["reply"] = httpx.Response(400, json={"detail": "sortBy must be one of views, ..."})
    with pytest.raises(ToolError, match="400.*sortBy must be one of"):
        await _call({"from": "2026-05-01", "sortBy": "comments"})


async def test_a_bigquery_failure_in_the_answer_becomes_a_tool_error(api):
    api["reply"] = httpx.Response(
        200, json={"items": [], "errorCode": "accessDenied", "errorMessage": "no access"}
    )
    with pytest.raises(ToolError, match="accessDenied.*no access"):
        await _call({"from": "2026-05-01"})


async def test_the_call_is_logged_to_stderr_never_stdout(api, capsys):
    await _call({"from": "2026-05-01", "topN": 3})
    captured = capsys.readouterr()
    assert "search_content_insights" not in captured.out
    logged = json.loads(captured.err.strip().splitlines()[-1])
    assert logged["message"] == "search_content_insights" and logged["topN"] == 3
