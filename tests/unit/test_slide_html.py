"""HTML cleanup and the browser screenshot contract."""

from pathlib import Path

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


async def test_a_background_that_did_not_load_is_an_error(tmp_path):
    """A missing background renders as a blank canvas with a placeholder icon."""
    page = "<html><body style='margin:0'><img src='background.jpg'></body></html>"
    with pytest.raises(slide_html.BackgroundMissingError, match="background.jpg"):
        await slide_html.screenshot(page, tmp_path / "s.jpg", tmp_path)


async def test_a_page_whose_background_loads_is_fine(tmp_path):
    from PIL import Image

    Image.new("RGB", (100, 100), "red").save(tmp_path / "background.jpg")
    page = "<html><body style='margin:0'><img src='background.jpg'></body></html>"
    out = await slide_html.screenshot(page, tmp_path / "s.jpg", tmp_path)
    assert out.exists()


async def test_a_page_with_no_images_at_all_is_fine(tmp_path):
    page = "<html><body style='margin:0;background:#333'></body></html>"
    out = await slide_html.screenshot(page, tmp_path / "s.jpg", tmp_path)
    assert out.exists()


async def test_a_relative_path_still_renders(tmp_path, monkeypatch):
    """file:// URIs need absolute paths; a relative project dir must still work."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "proj").mkdir()
    page = "<html><body style='margin:0;background:#222'></body></html>"
    out = await slide_html.screenshot(
        page, Path("proj/s.jpg"), Path("proj")
    )
    assert out.is_absolute()
    assert out.exists()


class TestDecorLibrary:
    """Section 9 of the design guidelines: 194 outline PNGs, recoloured."""

    def test_the_library_is_installed(self):
        assets = slide_html.decor_assets()
        assert len(assets) == 194
        assert "arrow 1.png" in assets

    def test_the_cache_holds_a_set_per_brand_colour(self):
        from instagram_marketing_agent.config import DECOR_COLOURS

        cache = slide_html.build_decor_cache()
        assert cache is not None
        for token in DECOR_COLOURS:
            assert (cache / token / "arrow 1.png").exists()

    def test_recolouring_keeps_the_shape_and_replaces_the_colour(self):
        """The alpha channel is the artwork; only the colour changes."""
        from PIL import Image

        from instagram_marketing_agent.config import DECOR_COLOURS, DECOR_DIR

        cache = slide_html.build_decor_cache()
        with Image.open(DECOR_DIR / "arrow 1.png") as original:
            source_alpha = original.convert("RGBA").getchannel("A").tobytes()
        with Image.open(cache / "turquoise" / "arrow 1.png") as tinted:
            rgba = tinted.convert("RGBA")
            assert rgba.getchannel("A").tobytes() == source_alpha
            opaque = [p for p in rgba.get_flattened_data() if p[3] > 200]
        expected = tuple(int(DECOR_COLOURS["turquoise"][i : i + 2], 16) for i in (1, 3, 5))
        assert all(p[:3] == expected for p in opaque)

    async def test_a_recoloured_element_renders_in_the_page(self, tmp_path):
        from PIL import Image

        page = (
            "<html><body style='margin:0;background:#fff'>"
            "<img src='decor/turquoise/arrow 1.png' width='400'>"
            "</body></html>"
        )
        out = await slide_html.screenshot(page, tmp_path / "s.jpg", tmp_path)
        with Image.open(out) as im:
            teal = sum(
                1
                for r, g, b in im.convert("RGB").get_flattened_data()
                if abs(r - 87) < 45 and abs(g - 202) < 45 and abs(b - 174) < 45
            )
        assert teal > 500, "the recoloured element did not render"

    def test_the_prompt_offers_the_library(self):
        from instagram_marketing_agent import llm
        from instagram_marketing_agent.config import POST_FORMAT

        rules = llm._layout_rules(POST_FORMAT)
        assert "DECORATIVE ELEMENTS" in rules
        assert "arrow 1.png" in rules
        # Masks do not render in headless Chromium; the assets are pre-tinted.
        assert "-webkit-mask" not in rules
