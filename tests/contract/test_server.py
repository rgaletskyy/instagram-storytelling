"""The MCP surface, exercised through the in-memory client."""

import pytest
from mcp import Client

from instagram_marketing_agent.client import _payload
from instagram_marketing_agent.server import mcp

pytestmark = pytest.mark.contract

EXPECTED_TOOLS = {
    "create_lifestyle_content",
    "create_post_campaign",
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


async def test_every_brand_resource_is_published():
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
    assert uris == {
        "content://slide-design-guidelines.md",
        "content://smm_composition_rules.md",
        "content://lifestyle-content-brief.md",
    }


@pytest.mark.parametrize(
    "uri,marker",
    [
        ("content://smm_composition_rules.md", "Scene Composition Rules"),
        ("content://slide-design-guidelines.md", "Slide Design System"),
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


async def test_both_campaign_formats_are_offered():
    """Stories and square feed posts are the same pipeline, different artboards."""
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"create_story_campaign", "create_post_campaign"} <= names


async def test_the_two_campaign_tools_take_the_same_arguments():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    story = set(tools["create_story_campaign"].input_schema["properties"])
    post = set(tools["create_post_campaign"].input_schema["properties"])
    assert story == post == {"topic", "slide_count", "verify"}


async def test_render_and_validate_accept_a_format():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("render_story_slide", "validate_slide"):
        assert "format" in tools[name].input_schema["properties"], name


async def test_the_lifestyle_brief_is_readable():
    async with Client(mcp) as client:
        contents = (
            await client.read_resource("content://lifestyle-content-brief.md")
        ).contents
    assert "Lifestyle Content Brief" in contents[0].text


async def test_lifestyle_content_defaults_to_three_images():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    schema = tools["create_lifestyle_content"].input_schema["properties"]
    assert schema["image_count"]["default"] == 3
