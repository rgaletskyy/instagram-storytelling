"""MCP server. Registration and marshalling only -- the logic lives in workflow.py.

Built on mcp.server.MCPServer: mcp.server.fastmcp does not exist in SDK v2.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import ffmpeg, llm, slide_html, workflow
from .config import (
    DEFAULT_LIFESTYLE_IMAGES,
    DEFAULT_SLIDES,
    DEFAULT_VIDEO_FRAMES,
    DESIGN_GUIDELINES,
    FORMATS,
    LIFESTYLE_BRIEF,
    STORY_FORMAT,
    STORYTELLING_RULES,
)
from .models import Product, SlideSpec

mcp = MCPServer(
    name="instagram-marketing-agent",
    title="Instagram Story Telling Agent",
    description="Builds Instagram story campaigns from local images or vide and a brief.",
    version="0.1.0",
)

# Failures we saw coming -- a bad slide count, a missing file, no ffmpeg. Raised as
# ToolError so the client sees the actual message; anything else is a crash and the
# SDK deliberately withholds its text.
_ANTICIPATED = (
    ValueError,
    FileNotFoundError,
    RuntimeError,
    ffmpeg.FFmpegMissingError,
)


def _reporting(fn: Callable) -> Callable:
    """Surface anticipated failures to the caller instead of a generic error."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except _ANTICIPATED as exc:
            raise ToolError(str(exc)) from exc

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _ANTICIPATED as exc:
            raise ToolError(str(exc)) from exc

    return wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper


def _campaign_payload(campaign) -> dict:
    """The shape both campaign tools return."""
    return {
        "output_dir": str(campaign.output_dir),
        "format": campaign.format_name,
        "slides": [str(p) for p in campaign.slide_paths],
        "script": campaign.script.model_dump(mode="json"),
        "missing_skus": campaign.missing_skus,
        "failed_slides": [list(f) for f in campaign.failed_slides],
        "verdicts": [v.model_dump(mode="json") for v in campaign.verdicts],
    }


# --- Workflow tools ----------------------------------------------------------


@mcp.tool()
@_reporting
async def create_story_campaign(
    topic: str | None = None,
    slide_count: int = DEFAULT_SLIDES,
    verify: bool = True,
) -> dict:
    """Run the whole campaign: describe input, write the script, render and verify."""
    campaign = await workflow.create_story_campaign(
        topic=topic, slide_count=slide_count, verify=verify
    )
    return _campaign_payload(campaign)


@mcp.tool()
@_reporting
async def create_post_campaign(
    topic: str | None = None,
    slide_count: int = DEFAULT_SLIDES,
    verify: bool = True,
) -> dict:
    """Same campaign, on a 1:1 square artboard for an Instagram feed post.

    Identical pipeline and brand rules to create_story_campaign -- only the
    artboard differs: 1080x1080 instead of 1080x1920, and no story UI to keep
    clear of, so the copy can use more of the frame.
    """
    campaign = await workflow.create_post_campaign(
        topic=topic, slide_count=slide_count, verify=verify
    )
    return _campaign_payload(campaign)


@mcp.tool()
@_reporting
async def create_lifestyle_content(
    topic: str | None = None,
    image_count: int = DEFAULT_LIFESTYLE_IMAGES,
    verify: bool = True,
) -> dict:
    """Generate lifestyle photography for a product named by SKU in the brief.

    Reuses the campaign building blocks -- SKU lookup, product-referenced
    generation, verification -- but stops at images: a lifestyle frame carries
    no copy, because the brief rejects text baked into the picture. The packshot
    is downloaded from the catalogue image URL, falling back to a photo in
    content/input/ when the row has none. Frames are 4:5 (1080x1350).

    `image_count` is per product: a brief naming three SKUs yields three sets.
    Defaults to 3 images each when the brief does not say how many.
    """
    return await workflow.create_lifestyle_content(
        topic=topic, image_count=image_count, verify=verify
    )


@mcp.tool()
@_reporting
async def regenerate_slide(project_dir: str, slide_index: int, comment: str) -> str:
    """Redo one slide of a saved campaign from a comment, leaving the others alone."""
    return str(await workflow.regenerate_slide(project_dir, slide_index, comment))


@mcp.tool()
@_reporting
def save_project(output_dir: str) -> str:
    """Report a saved campaign folder. Campaigns are saved as they are generated."""
    path = Path(output_dir)
    if not (path / "script.json").exists():
        raise ValueError(f"no campaign at {output_dir}")
    return str(path)


# --- Content tools -----------------------------------------------------------


@mcp.tool()
@_reporting
def get_product(skus: list[str]) -> dict:
    """Look product SKUs up in the catalogue."""
    found, missing = workflow.get_products(skus)
    return {
        "products": [p.model_dump(mode="json") for p in found],
        "missing": missing,
    }


@mcp.tool()
@_reporting
async def describe_image(image_path: str) -> str:
    """Describe an image in detail."""
    return await llm.describe_image(image_path)


@mcp.tool()
@_reporting
async def generate_image(
    prompt: str, out_path: str, references: list[str] | None = None
) -> str:
    """Generate a 9:16 background image. The prompt must not contain a URL.

    Pass `references` -- paths to real product photographs -- on any image that
    shows the product. Without them the model invents plausible but wrong
    packaging. Describe the setting in `prompt`, not the label.
    """
    return str(
        await llm.generate_image(
            prompt,
            out_path,
            references=[Path(r) for r in references] if references else None,
        )
    )


@mcp.tool()
@_reporting
async def generate_storytelling_script(
    topic: str,
    descriptions: list[str],
    products: list[dict] | None = None,
    slide_count: int = DEFAULT_SLIDES,
) -> dict:
    """Write the campaign script for a topic."""
    script = await llm.generate_script(
        topic=topic,
        descriptions=descriptions,
        products=[Product.model_validate(p) for p in (products or [])],
        slide_count=slide_count,
    )
    return script.model_dump(mode="json")


@mcp.tool()
@_reporting
async def render_story_slide(
    background_path: str,
    overlay_text: str,
    out_path: str,
    role: str = "solution",
    slide_index: int = 1,
    format: str = "story",
) -> str:
    """Lay a slide out as HTML over a background and screenshot it to a JPG.

    `format` is "story" (1080x1920) or "post" (1080x1080).

    The layout model sees the background, so copy is placed around the subject
    rather than stamped at a fixed position.
    """
    background = Path(background_path)
    slide = SlideSpec(
        index=slide_index,
        role=role,
        image_prompt="",
        overlay_text=overlay_text,
    )
    fmt = FORMATS.get(format, STORY_FORMAT)
    html = await llm.generate_slide_html(slide, background, fmt=fmt)
    return str(
        await slide_html.screenshot(html, Path(out_path), background.parent, fmt)
    )


@mcp.tool()
@_reporting
async def validate_slide(
    image_path: str,
    overlay_text: str,
    role: str = "solution",
    slide_index: int = 1,
    format: str = "story",
) -> dict:
    """Check a rendered slide against the design guidelines and its own copy."""
    slide = SlideSpec(
        index=slide_index,
        role=role,
        image_prompt="",
        overlay_text=overlay_text,
    )
    verdict = await llm.verify_slide(
        Path(image_path), slide, FORMATS.get(format, STORY_FORMAT)
    )
    return verdict.model_dump(mode="json")


# --- Video tools -------------------------------------------------------------


@mcp.tool()
@_reporting
async def transcribe_video(video_path: str, out_dir: str | None = None) -> str:
    """Extract the audio track and transcribe it. Empty when there is no audio.

    With `out_dir`, the transcript is also written there as `<name>-transcript.txt`.
    """
    import tempfile

    video = Path(video_path)
    with tempfile.TemporaryDirectory() as tmp:
        audio = await ffmpeg.extract_audio(video, Path(tmp) / "audio.wav")
        if audio is None:
            return ""
        transcript = await llm.transcribe_audio(audio)

    if out_dir and transcript:
        destination = Path(out_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{video.stem}-transcript.txt").write_text(
            transcript, encoding="utf-8"
        )
    return transcript


@mcp.tool()
@_reporting
async def describe_video(
    video_path: str,
    frame_count: int = DEFAULT_VIDEO_FRAMES,
    out_dir: str | None = None,
) -> str:
    """Describe a video from frames sampled across it, plus its transcript.

    `frame_count` is clamped to 5-10: enough to follow the clip, capped so a
    long video does not fan out into dozens of vision calls. With `out_dir`, the
    sampled frames and the transcript are kept there instead of discarded.
    """
    described = await workflow.describe_video(
        Path(video_path),
        frame_count,
        artifacts_dir=Path(out_dir) if out_dir else None,
    )
    return described.as_context()


# --- Resources ---------------------------------------------------------------


@mcp.resource(
    "content://story-design-guidelines.md",
    name="Story design guidelines",
    mime_type="text/markdown",
)
def design_guidelines() -> str:
    """Brand rules for how a story slide must look."""
    return DESIGN_GUIDELINES.read_text(encoding="utf-8")


@mcp.resource(
    "content://lifestyle-content-brief.md",
    name="Lifestyle content brief",
    mime_type="text/markdown",
)
def lifestyle_brief() -> str:
    """Standing brief for lifestyle product photography."""
    return LIFESTYLE_BRIEF.read_text(encoding="utf-8")


@mcp.resource(
    "content://story-telling-rules.md",
    name="Story telling rules",
    mime_type="text/markdown",
)
def storytelling_rules() -> str:
    """Rules for what a story says and in what order. Basic recommendations how to build good story telling."""
    return STORYTELLING_RULES.read_text(encoding="utf-8")


# --- Prompt ------------------------------------------------------------------


@mcp.prompt()
def story_campaign(topic: str, slide_count: int = DEFAULT_SLIDES) -> str:
    """Guide a chat client through building a instagram story campaign / story telling."""
    return f"""Build an Instagram story campaign about: {topic!r} ({slide_count} slides).

Read both resources first -- they are normative, not background reading:
- content://story-telling-rules.md   what the story says, and in what order
- content://story-design-guidelines.md   how a slide must look

## The quick path

Call `create_story_campaign(topic={topic!r}, slide_count={slide_count})` for a
9:16 story, or `create_post_campaign(...)` for a 1:1 square feed post. Both take
the same arguments and run the same pipeline -- only the artboard differs, so
pick by where the user intends to publish. It runs
everything -- product lookup, image description, script, backgrounds, layout,
rendering and verification -- and saves a project folder. Report the output
folder, any slides that failed, and any verification verdict that did not pass.
Pass `verify=False` to skip the design review pass and finish roughly twice as
fast.

## The step-by-step path

Use these when the user wants to steer each stage, inspect intermediate results,
or redo one piece without regenerating the campaign. Every tool works on its own,
so you can start anywhere and stop anywhere.

Understand the inputs:
- `get_product(skus)` -- look SKUs up in the catalogue. SKUs are written inline in
  the brief, e.g. "Face It up (BO-FIU150)". Returns name, price, description,
  image URL and the product page URL, plus any SKU that was not found.
- `describe_image(image_path)` -- what a supplied photo actually shows. Run this
  on each file in content/input/ before writing copy.
- `describe_video(video_path)` / `transcribe_video(video_path)` -- frames plus
  spoken content, when a clip was supplied. These need ffmpeg; nothing else does.

Write the script:
- `generate_storytelling_script(topic, descriptions, products, slide_count)` --
  returns a slide per entry with `image_prompt`, `overlay_text`, `ig_notes`,
  `role` and `shows_product`. Between 3 and 7 slides; hook first, exactly one
  cta, and it goes last.

Build one slide at a time:
- `generate_image(prompt, out_path, references)` -- the background. It renders
  9:16 by default; the campaign tools set the aspect to match their format. On any
  slide where `shows_product` is true, pass the real product photograph in
  `references`, and describe the SETTING in `prompt`, never the label. Without a
  reference the model invents packaging that looks plausible and is wrong. Never
  put a URL or web address in `prompt`.
- `render_story_slide(background_path, overlay_text, out_path, role, slide_index,
  format)` -- lays the copy out over that background in HTML and screenshots it.
  `format` is "story" (1080x1920) or "post" (1080x1080). The layout is composed with the background in view, so the copy is
  placed around the subject rather than at a fixed position.
- `validate_slide(image_path, overlay_text, role, slide_index)` -- reviews the
  rendered slide against the design guidelines. Returns `passed` plus specific
  `issues`. Worth calling after any manual render.
- `regenerate_slide(project_dir, slide_index, comment)` -- redo one slide of a
  saved campaign from a written note, leaving the others untouched.
- `save_project(output_dir)` -- confirm where a campaign was written.

## Things that are easy to get wrong

- The product page URL belongs in the script and the link sticker, never in an
  image prompt and never rendered into a slide.
- Copy goes in the language of the brief.
- On a story, keep text inside y=250..1670 -- Instagram's own UI covers the top
  and bottom bands. A square post has no such UI, so only the margin is reserved.
- Interactive stickers are notes for the human posting, not drawn on the image.

Input files live in content/input/, finished projects in content/output/."""


def main() -> int:
    # ffmpeg is checked lazily: it is only needed when video input is supplied.
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
