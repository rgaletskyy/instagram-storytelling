"""HTML cleanup and the browser screenshot contract."""

import pytest

from instagram_marketing_agent import slide_html
from instagram_marketing_agent.config import CANVAS_H, CANVAS_W

pytestmark = pytest.mark.unit

DOC = "<html><body>hi</body></html>"


@pytest.mark.parametrize(
    "raw",
    [
        DOC,
        f"```html\n{DOC}\n```",
        f"```\n{DOC}\n```",
        f"  \n{DOC}\n  ",
    ],
)
def test_markdown_fences_are_stripped(raw):
    assert slide_html.clean_html(raw) == DOC


def test_clean_html_handles_empty():
    assert slide_html.clean_html("") == ""


async def test_screenshot_produces_a_story_sized_jpeg(tmp_path):
    from PIL import Image

    html = (
        "<html><body style='margin:0'>"
        f"<div style='width:{CANVAS_W}px;height:{CANVAS_H}px;background:#123456'></div>"
        "</body></html>"
    )
    out = await slide_html.screenshot(html, tmp_path / "s.jpg", tmp_path)
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (CANVAS_W, CANVAS_H)
        assert im.format == "JPEG"


async def test_temp_page_is_cleaned_up(tmp_path):
    await slide_html.screenshot(DOC, tmp_path / "s.jpg", tmp_path)
    assert list(tmp_path.glob("*.html")) == []


async def test_a_post_renders_square(tmp_path):
    from PIL import Image

    from instagram_marketing_agent.config import POST_FORMAT

    html = "<html><body style='margin:0;background:#123456'></body></html>"
    out = await slide_html.screenshot(html, tmp_path / "p.jpg", tmp_path, POST_FORMAT)
    with Image.open(out) as im:
        assert im.size == (1080, 1080)


def test_the_two_formats_differ_only_in_artboard():
    from instagram_marketing_agent.config import POST_FORMAT, STORY_FORMAT

    assert STORY_FORMAT.aspect_ratio == "9:16"
    assert POST_FORMAT.aspect_ratio == "1:1"
    assert POST_FORMAT.width == POST_FORMAT.height == 1080
    # The text budget is a fraction, so it scales with the artboard.
    assert POST_FORMAT.text_block_max_h < STORY_FORMAT.text_block_max_h
