"""hd-marketing-mcp: tools for HealthyDoggo's SMM managers. Implements specs/marketing-mcp.md.

    uv run python src/mcp-server.py                         # HTTP on :8080, as on Cloud Run
    MCP_TRANSPORT=stdio uv run python src/mcp-server.py     # for a local MCP client

Over HTTP every request needs a Google sign-in from an allowlisted account
(see auth.py), and the server will not start without it configured. Over
stdio there is no network to guard: whoever starts the process is the user.

Only search_knowledge_base, search_content_insights, generate_image and
generate_slide exist so far; the spec's other tools come later.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

import auth
from tools import generate_image as image_tool
from tools import generate_slide as slide_tool
from tools import search_content_insights as insights_tool
from tools import search_knowledge_base as search_tool

mcp = FastMCP(
    name="hd-marketing-mcp",
    instructions=(
        "Tools for HealthyDoggo's SMM managers: find products, Instagram conversations "
        "and photos or videos in the content library, and see how the account's Instagram "
        "posts, reels and stories performed. Creaete or edit images, write copy text for psots, generate slides for posts and stories, validate content."
    ),
)
mcp.tool(
    search_tool.search_knowledge_base, name=search_tool.NAME, description=search_tool.DESCRIPTION
)
mcp.tool(
    insights_tool.search_content_insights,
    name=insights_tool.NAME,
    description=insights_tool.DESCRIPTION,
)
mcp.tool(image_tool.generate_image, name=image_tool.NAME, description=image_tool.DESCRIPTION)
mcp.tool(slide_tool.generate_slide, name=slide_tool.NAME, description=slide_tool.DESCRIPTION)


def main() -> None:
    if os.environ.get("MCP_TRANSPORT", "http") == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.auth = auth.build_provider()
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        path="/mcp",
        # Every request stands alone: Cloud Run may send consecutive requests
        # of one session to different instances.
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
