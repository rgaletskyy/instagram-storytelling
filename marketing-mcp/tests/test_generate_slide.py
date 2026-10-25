"""generate_slide and SlideRenderer, with the download and Claude faked.

The renders run a real headless Chromium; they are skipped where Playwright's
browser is not installed (`uv run playwright install chromium`).
"""

import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from PIL import Image as PILImage

from tools import generate_slide as tool
from tools.image_generation_service import ImageGenerator
from tools.slide_html_service import (
    FORMATS,
    GOOGLE_FONTS_HREF,
    SlideError,
    SlideRenderer,
    clean_html,
    decor_assets,
    tinted_decor,
)

SERVER = Path(__file__).resolve().parents[1] / "src" / "mcp-server.py"


def _server():
    spec = importlib.util.spec_from_file_location("mcp_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


def _chromium_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


needs_chromium = pytest.mark.skipif(not _chromium_installed(), reason="no Playwright Chromium")

RED = (200, 30, 30)


def _jpeg(size=(1200, 2000), colour=RED) -> bytes:
    out = io.BytesIO()
    PILImage.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


def _page(body: str = "") -> str:
    return (
        f'<html><head><link rel="stylesheet" href="{GOOGLE_FONTS_HREF}"><style>'
        "body{margin:0;overflow:hidden;position:relative}"
        "img.bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
        f'</style></head><body><img class="bg" src="background.jpg">{body}</body></html>'
    )


class FakeClaude:
    """Stands in for AsyncAnthropic; answers each layout request with the next page."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.requests = []
        self.messages = SimpleNamespace(parse=self._parse)

    async def _parse(self, **kwargs):
        self.requests.append(kwargs)
        page = self.pages.pop(0) if self.pages else None
        parsed = SimpleNamespace(html=page, placement_reason="") if page else None
        return SimpleNamespace(parsed_output=parsed, stop_reason="end_turn")


# --- SlideRenderer ------------------------------------------------------------


def test_markdown_fences_are_stripped():
    assert clean_html("```html\n<html></html>\n```") == "<html></html>"


def test_decor_is_tinted_to_a_brand_colour():
    name = decor_assets()[0]
    image = PILImage.open(io.BytesIO(tinted_decor("pink", name))).convert("RGBA")
    pixels = image.load()
    opaque = [
        pixels[x, y]
        for x in range(image.width)
        for y in range(image.height)
        if pixels[x, y][3] == 255
    ]
    assert opaque and all(p[:3] == (0xFF, 0x80, 0x80) for p in opaque)
    assert tinted_decor("purple", name) is None
    assert tinted_decor("pink", "../../secret.png") is None


async def test_layout_sends_the_background_copy_and_safe_area():
    claude = FakeClaude(_page())
    html = await SlideRenderer(client=claude).layout(
        "a price slide", "Шампунь\n299 грн", _jpeg(), FORMATS["9:16"]
    )
    assert html == _page()
    image, text = claude.requests[0]["messages"][0]["content"]
    assert base64.b64decode(image["source"]["data"]) == _jpeg()
    assert "a price slide" in text["text"] and "Шампунь\n299 грн" in text["text"]
    assert "y=250px and y=1670px" in text["text"]
    assert "Design" in claude.requests[0]["system"][0]["text"]


async def test_no_layout_is_an_error():
    with pytest.raises(SlideError, match="no layout"):
        await SlideRenderer(client=FakeClaude()).layout("x", "y", _jpeg(), FORMATS["1:1"])


async def test_a_missing_api_key_is_an_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SlideError, match="ANTHROPIC_API_KEY"):
        await SlideRenderer().layout("x", "y", _jpeg(), FORMATS["1:1"])


async def test_an_unknown_aspect_ratio_is_refused():
    with pytest.raises(SlideError, match="aspect ratio"):
        await SlideRenderer(client=FakeClaude()).render("x", "y", _jpeg(), "16:9")


@needs_chromium
@pytest.mark.parametrize("ratio", ["9:16", "4:5", "1:1"])
async def test_a_render_is_the_artboard_size_with_its_background(ratio):
    fmt = FORMATS[ratio]
    name = decor_assets()[0]
    page = _page(f'<img src="decor/white/{name}" style="position:absolute;top:0;width:100px">')
    slide = await SlideRenderer(client=FakeClaude(page)).render("x", "y", _jpeg(), ratio)
    image = PILImage.open(io.BytesIO(slide))
    assert image.format == "JPEG" and image.size == (fmt.width, fmt.height)
    r, g, b = image.getpixel((fmt.width // 2, fmt.height // 2))
    assert r > 150 and g < 80 and b < 80  # the red background


@needs_chromium
async def test_a_page_reaching_elsewhere_is_laid_out_again():
    bad = _page('<img src="http://169.254.169.254/computeMetadata/v1/x.png">')
    claude = FakeClaude(bad, _page())
    await SlideRenderer(client=claude).render("x", "y", _jpeg(), "1:1")
    assert len(claude.requests) == 2
    retry = claude.requests[1]["messages"][0]["content"][1]["text"]
    assert "169.254.169.254" in retry and "did not load" in retry


@needs_chromium
async def test_a_page_still_broken_after_the_retry_is_an_error():
    bad = _page('<img src="logo.png">')
    with pytest.raises(SlideError, match="logo.png"):
        await SlideRenderer(client=FakeClaude(bad, bad)).render("x", "y", _jpeg(), "1:1")


# --- the tool -------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    """Fakes the download and the renderer."""
    state = {"files": {}, "renders": []}

    async def render(subject, overlay_text, background, aspect_ratio):
        state["renders"].append((subject, overlay_text, background, aspect_ratio))
        return _jpeg((10, 10))

    def handler(request):
        return state["files"].get(str(request.url), httpx.Response(404))

    monkeypatch.setattr(
        tool, "_downloader", ImageGenerator(http_transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(tool, "_renderer", SimpleNamespace(render=render))
    return state


async def _call(arguments):
    async with Client(_server()) as client:
        return await client.call_tool("generate_slide", arguments, raise_on_error=True)


async def test_the_tool_is_listed_with_the_spec_parameters():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["generate_slide"].input_schema
    assert set(schema["properties"]) == {"subject", "backgroundImage", "overlayText", "aspectRatio"}
    assert sorted(schema["required"]) == ["backgroundImage", "overlayText", "subject"]


async def test_the_slide_is_returned_as_an_image(world):
    world["files"]["https://x.test/dog.jpg"] = httpx.Response(
        200, content=_jpeg((3000, 4000)), headers={"content-type": "image/jpeg"}
    )
    result = await _call(
        {
            "subject": "price slide",
            "backgroundImage": "https://x.test/dog.jpg",
            "overlayText": " 299 грн ",
        }
    )
    subject, text, background, ratio = world["renders"][0]
    assert (subject, text, ratio) == ("price slide", "299 грн", "9:16")
    assert max(PILImage.open(io.BytesIO(background)).size) == 2048
    assert result.content[0].type == "image"
    assert base64.b64decode(result.content[0].data) == _jpeg((10, 10))


async def test_a_background_that_cannot_be_downloaded_fails_the_call(world):
    with pytest.raises(ToolError, match="download failed"):
        await _call(
            {"subject": "x", "backgroundImage": "https://x.test/no.jpg", "overlayText": "y"}
        )
    assert world["renders"] == []


async def test_empty_copy_is_refused(world):
    with pytest.raises(ToolError, match="overlayText"):
        await _call({"subject": "x", "backgroundImage": "https://x.test/a.jpg", "overlayText": " "})
