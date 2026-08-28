"""In-memory MCP client.

mcp.Client accepts the MCPServer object directly, so the module path exercises the
same tools a chat client calls, with no subprocess and no transport wiring.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import Client

from .config import DEFAULT_SLIDES
from .server import mcp


def _payload(result: Any) -> Any:
    """Pull the structured result out of an MCP tool response."""
    structured = getattr(result, "structured_content", None)
    if structured:
        # MCPServer wraps a non-dict return value under "result".
        return structured.get("result", structured)
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except (ValueError, TypeError):
                return block.text
    return result


async def call(name: str, **arguments: Any) -> Any:
    """Call any tool on the server by name."""
    async with Client(mcp) as client:
        return _payload(await client.call_tool(name, arguments))


async def run_campaign(
    topic: str | None = None, slide_count: int = DEFAULT_SLIDES
) -> Any:
    """Run the full campaign through the MCP surface."""
    return await call("create_story_campaign", topic=topic, slide_count=slide_count)


async def read_resource(uri: str) -> str:
    """Read one of the brand documents."""
    async with Client(mcp) as client:
        result = await client.read_resource(uri)
        return "\n".join(
            getattr(c, "text", "") for c in getattr(result, "contents", []) or []
        )
