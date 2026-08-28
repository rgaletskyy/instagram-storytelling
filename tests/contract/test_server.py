"""The MCP surface, exercised through the in-memory client."""

import pytest
from mcp import Client

from instagram_story_agent.client import _payload
from instagram_story_agent.server import mcp

pytestmark = pytest.mark.contract

EXPECTED_TOOLS = {
    "create_story_campaign",
    "describe_image",
    "describe_video",
    "generate_image",
    "generate_storytelling_script",
    "get_product",
    "regenerate_slide",
    "render_story_slide",
    "save_project",
    "transcribe_video",
    "validate_slide",
}


async def test_every_contracted_tool_is_registered():
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == EXPECTED_TOOLS


async def test_the_verifier_is_exposed_as_a_tool():
    """validate_slide was deferred in the first iteration; it now exists."""
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "validate_slide" in names


async def test_both_brand_resources_are_published():
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
    assert uris == {
        "content://story-design-guidelines.md",
        "content://story-telling-rules.md",
    }


@pytest.mark.parametrize(
    "uri,marker",
    [
        ("content://story-telling-rules.md", "Story Telling Rules"),
        ("content://story-design-guidelines.md", "Story Design System"),
    ],
)
async def test_resources_are_served_verbatim(uri, marker):
    async with Client(mcp) as client:
        contents = (await client.read_resource(uri)).contents
    assert marker in contents[0].text


async def test_campaign_prompt_is_registered():
    async with Client(mcp) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
    assert "story_campaign" in names


async def test_get_product_reports_hits_and_misses():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_product", {"skus": ["BO-FIU150", "NOPE-1"]}
        )
    payload = _payload(result)
    assert [p["sku"] for p in payload["products"]] == ["BO-FIU150"]
    assert payload["missing"] == ["NOPE-1"]


async def test_create_story_campaign_rejects_an_out_of_range_slide_count():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "create_story_campaign", {"topic": "test", "slide_count": 9}
        )
    assert result.is_error
    # The anticipated failure must reach the caller, not a generic message.
    assert "between 3 and 7" in result.content[0].text
