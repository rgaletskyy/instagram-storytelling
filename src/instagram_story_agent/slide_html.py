"""Render a slide by screenshotting HTML/CSS in a headless browser.

CSS gives real typography, layout and safe-zone control, and lets the layout be
placed around whatever is in the background image -- which a burnt-in overlay
filter cannot do.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import async_playwright

from .config import CANVAS_H, CANVAS_W, SCREENSHOT_QUALITY

_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)


def clean_html(raw: str) -> str:
    """Strip markdown fences a model may wrap the document in."""
    return _FENCE_RE.sub("", raw or "").strip()


async def screenshot(html: str, out_path: Path, base_dir: Path) -> Path:
    """Write `html` beside its assets and screenshot it at story dimensions.

    The document is written into base_dir so relative asset references such as
    background.jpg resolve, and loaded over file:// rather than set_content --
    set_content has no base URL, so relative images would silently fail.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base_dir.mkdir(parents=True, exist_ok=True)
    page_file = base_dir / f".{out_path.stem}.html"
    page_file.write_text(clean_html(html), encoding="utf-8")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": CANVAS_W, "height": CANVAS_H},
                device_scale_factor=1,
            )
            await page.goto(page_file.as_uri(), wait_until="networkidle")
            # Webfonts resolve after load; screenshotting early yields fallbacks.
            await page.evaluate("() => document.fonts.ready")
            await page.screenshot(
                path=str(out_path),
                type="jpeg",
                quality=SCREENSHOT_QUALITY,
                clip={"x": 0, "y": 0, "width": CANVAS_W, "height": CANVAS_H},
            )
        finally:
            await browser.close()

    page_file.unlink(missing_ok=True)
    return out_path
