"""Render a slide by screenshotting HTML/CSS in a headless browser.

CSS gives real typography, layout and safe-zone control, and lets the layout be
placed around whatever is in the background image -- which a burnt-in overlay
filter cannot do.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import async_playwright

from .config import SCREENSHOT_QUALITY, STORY_FORMAT, CanvasFormat

_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)

# Any <img> that failed to load, plus any CSS background whose url() 404s.
# naturalWidth is 0 for an image the browser could not decode.
BROKEN_IMAGE_PROBE = """() => {
  const broken = [];
  for (const img of document.images) {
    if (!img.complete || img.naturalWidth === 0) broken.push(img.getAttribute('src'));
  }
  return broken.length ? broken.join(', ') : null;
}"""


class BackgroundMissingError(RuntimeError):
    """The rendered page could not load its background image."""


def clean_html(raw: str) -> str:
    """Strip markdown fences a model may wrap the document in."""
    return _FENCE_RE.sub("", raw or "").strip()


async def screenshot(
    html: str,
    out_path: Path,
    base_dir: Path,
    fmt: CanvasFormat = STORY_FORMAT,
) -> Path:
    """Write `html` beside its assets and screenshot it at the format's size.

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
                viewport={"width": fmt.width, "height": fmt.height},
                device_scale_factor=1,
            )
            await page.goto(page_file.as_uri(), wait_until="networkidle")
            # Webfonts resolve after load; screenshotting early yields fallbacks.
            await page.evaluate("() => document.fonts.ready")

            broken = await page.evaluate(BROKEN_IMAGE_PROBE)
            if broken:
                # A background that did not load renders as a blank canvas with
                # a placeholder icon. Raising here lets the caller retry rather
                # than shipping an empty slide that only the verifier catches.
                raise BackgroundMissingError(
                    f"the page references {broken} but it did not load; "
                    f"the background must be referenced as 'background.jpg'"
                )
            await page.screenshot(
                path=str(out_path),
                type="jpeg",
                quality=SCREENSHOT_QUALITY,
                clip={"x": 0, "y": 0, "width": fmt.width, "height": fmt.height},
            )
        finally:
            await browser.close()

    page_file.unlink(missing_ok=True)
    return out_path


def normalize(image: Path, fmt: CanvasFormat) -> Path:
    """Resize a generated frame to the format's exact delivery size.

    Gemini returns its own resolution at roughly the requested aspect, which is
    close to but not exactly 4:5. Section 9 of the lifestyle brief specifies
    delivery dimensions, so centre-crop to the exact aspect and resize.
    """
    from PIL import Image

    with Image.open(image) as im:
        im = im.convert("RGB")
        target = fmt.width / fmt.height
        width, height = im.size
        if width / height > target:
            new_w = int(height * target)
            box = ((width - new_w) // 2, 0, (width - new_w) // 2 + new_w, height)
        else:
            new_h = int(width / target)
            box = (0, (height - new_h) // 2, width, (height - new_h) // 2 + new_h)
        im.crop(box).resize(
            (fmt.width, fmt.height), Image.LANCZOS
        ).save(image, "JPEG", quality=SCREENSHOT_QUALITY)
    return image
