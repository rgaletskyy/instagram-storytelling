"""HTML cleanup and the browser screenshot contract."""

import pytest

from instagram_story_agent import slide_html
from instagram_story_agent.config import CANVAS_H, CANVAS_W

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
