"""Slides: Claude lays the copy out as HTML/CSS over the background, and a
headless Chromium screenshots it.

CSS gives real typography, layout and safe-zone control, and lets the layout be
placed around whatever is in the background image -- which a burnt-in overlay
filter cannot do. The model sees the actual background, so it can put the copy
in empty space instead of stamping text at a fixed position.

The page is served from memory under a made-up origin: its document, the
background and the decorative elements are answered by a request handler, the
brand fonts come from Google Fonts, and every other request is refused, so a
model-written page can reach nothing else -- not the disk, not the metadata
server.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

LAYOUT_MODEL = os.environ.get("SLIDE_LAYOUT_MODEL", "claude-opus-5-5")
LAYOUT_MAX_TOKENS = 16000
# A page whose images did not load is laid out once more, told why.
LAYOUT_RETRIES = 1

RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
DESIGN_GUIDELINES = RESOURCES_DIR / "slide-design-guidelines.md"
DECOR_DIR = RESOURCES_DIR / "png"
# Section 2.1 of the design guidelines. The library ships as dark outline art
# and must be recoloured; headless Chromium does not render CSS masks, so the
# tint is baked in Python instead.
DECOR_COLOURS = {
    "turquoise": "#57CAAE",
    "pink": "#FF8080",
    "brown": "#5F3D09",
    "white": "#FFFFFF",
    "grey": "#616161",
}

# Section 1 of the design guidelines.
SIDE_MARGIN = 72
HEADLINE_MAX_PX = 64
BODY_MAX_PX = 34
# The text block, including whatever card or scrim sits behind it. Left
# unbounded the model reaches for a full-bleed band that lands on the subject.
TEXT_BLOCK_MAX_FRACTION = 0.27
SCREENSHOT_QUALITY = 92
# Larger than any artboard side, so the background is not upscaled.
BACKGROUND_MAX_SIDE = 2048
# Each render is a Chromium; a few at once is all an instance has memory for.
MAX_BROWSERS = 2

GOOGLE_FONTS_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=Bitter:wght@700;800&family=Noto+Sans:wght@400;600;700&display=swap"
)
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
PAGE_ORIGIN = "https://slide.invalid"

_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)

# Any <img> that failed to load. naturalWidth is 0 for an image the browser
# could not decode.
BROKEN_IMAGE_PROBE = """() => {
  const broken = [];
  for (const img of document.images) {
    if (!img.complete || img.naturalWidth === 0) broken.push(img.getAttribute('src'));
  }
  return broken.length ? broken.join(', ') : null;
}"""


class SlideError(RuntimeError):
    """The slide could not be laid out or rendered."""


class BackgroundMissingError(SlideError):
    """The rendered page could not load an image it references."""


@dataclass(frozen=True)
class CanvasFormat:
    """An artboard: its size and where text may go."""

    name: str
    width: int
    height: int
    safe_top: int
    safe_bottom: int
    safe_note: str

    @property
    def text_block_max_h(self) -> int:
        return int(self.height * TEXT_BLOCK_MAX_FRACTION)


_POST_NOTE = (
    "a feed post has no story UI over it, so only the margin is reserved; "
    "keep clear of the very edge so nothing is clipped in a crop"
)
FORMATS = {
    "9:16": CanvasFormat(
        name="story",
        width=1080,
        height=1920,
        safe_top=250,
        safe_bottom=1670,
        safe_note=(
            "the top and bottom bands are covered by Instagram's progress bar, "
            "avatar and reply field"
        ),
    ),
    "4:5": CanvasFormat(
        name="portrait post",
        width=1080,
        height=1350,
        safe_top=SIDE_MARGIN,
        safe_bottom=1350 - SIDE_MARGIN,
        safe_note=_POST_NOTE,
    ),
    "1:1": CanvasFormat(
        name="square post",
        width=1080,
        height=1080,
        safe_top=SIDE_MARGIN,
        safe_bottom=1080 - SIDE_MARGIN,
        safe_note=_POST_NOTE,
    ),
}


def clean_html(raw: str) -> str:
    """Strip markdown fences a model may wrap the document in."""
    return _FENCE_RE.sub("", raw or "").strip()


def decor_assets() -> list[str]:
    """Filenames in the decorative element library, or empty when absent."""
    if not DECOR_DIR.is_dir():
        return []
    return sorted(p.name for p in DECOR_DIR.glob("*.png"))


@cache
def tinted_decor(colour: str, name: str) -> bytes | None:
    """One library element recoloured to a brand token, or None if either is unknown.

    The alpha channel is kept and the colour replaced, which is exact and
    cannot fail in the page.
    """
    hex_colour = DECOR_COLOURS.get(colour)
    source = DECOR_DIR / name
    if hex_colour is None or name not in decor_assets() or not source.is_file():
        return None
    from PIL import Image

    rgb = tuple(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    with Image.open(source) as im:
        alpha = im.convert("RGBA").getchannel("A")
        tinted = Image.new("RGBA", im.size, (*rgb, 255))
        tinted.putalpha(alpha)
        out = io.BytesIO()
        tinted.save(out, format="PNG")
    return out.getvalue()


@cache
def _guidelines() -> str:
    return DESIGN_GUIDELINES.read_text(encoding="utf-8")


class _SlideHTML(BaseModel):
    """A complete standalone HTML document for one slide."""

    html: str
    placement_reason: str = ""


def _layout_system() -> list[dict]:
    """System prompt with the design guidelines, cached across slides."""
    return [
        {
            "type": "text",
            "text": (
                "You lay out Instagram story and post slides as HTML and CSS for the "
                "HealthyDoggo brand. The design system below is normative.\n\n" + _guidelines()
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _decor_rules() -> str:
    """How to reach and recolour the decorative element library.

    Section 9 of the design guidelines catalogues the assets and its own rules
    govern how many may appear; this only explains the mechanics.
    """
    assets = decor_assets()
    if not assets:
        return ""
    return (
        "\n\nDECORATIVE ELEMENTS\n"
        f"The library from section 9 is available: {len(assets)} elements, "
        "already recoloured into the brand palette. Reference one as a plain "
        "image:\n"
        '  <img src="decor/turquoise/arrow 1.png" style="position:absolute;'
        'top:340px;left:380px;width:220px">\n'
        f"Colour folders: {', '.join(DECOR_COLOURS)}. Pick the one that suits "
        "the slide -- turquoise is the primary accent, pink is for promo and "
        "discounts, and white reads on a photograph. Use the filenames exactly "
        "as listed, spaces included.\n"
        "Obey section 9's limits: one arrow per slide, never mix the thin "
        "sketch and bold brush arrow families, one speech bubble per slide, at "
        "most two sparkle elements, and no sparkle on educational or "
        "medical-claim slides. Keep an element under 220px unless it is the "
        "arrow, and never let one cover the product, the dog's face or the "
        "copy. Decoration is optional -- a clean slide beats a decorated one.\n"
        "Available files:\n" + ", ".join(assets)
    )


def _layout_rules(fmt: CanvasFormat) -> str:
    """The layout contract, sized to the artboard being rendered."""
    return f"""Return one complete standalone HTML document.

Hard requirements:
- <body> is exactly {fmt.width}x{fmt.height} px, margin 0, overflow hidden.
- The supplied background image is the file `background.jpg` in the same folder.
  Use it as a full-bleed layer with object-fit: cover.
- Load the brand fonts with:
  <link rel="stylesheet" href="{GOOGLE_FONTS_HREF}">
  Headings use 'Bitter', body copy uses 'Noto Sans'. Use no other typeface.
- All text and any CTA must sit between y={fmt.safe_top}px and y={fmt.safe_bottom}px,
  with at least {SIDE_MARGIN}px clear on the left and right --
  {fmt.safe_note}.

THE TEXT BLOCK MUST BE SMALL AND MUST NOT COVER THE SUBJECT.
Treat the card, panel, scrim or gradient behind the copy as part of the text
block: what matters is the whole shape, not just the letters.
- The entire text block is at most {fmt.text_block_max_h}px tall -- about a
  quarter of the frame. If the copy will not fit, reduce the type size, not the
  margins.
- It is NEVER full-bleed. Inset it at least {SIDE_MARGIN}px from both edges so
  the photograph is visible down both sides of it.
- Headline at most {HEADLINE_MAX_PX}px, body copy at most {BODY_MAX_PX}px.
  Keep the headline to two lines and the body to two lines.
- FIRST look at the photograph and locate the dog's eyes and face, the product,
  and any hands. Then place the block in genuinely empty space -- sky, wall,
  floor, blurred background, a plain surface. The block must not touch any of
  those subjects, and its lower and upper edges must not cut across the dog's
  head. A band whose edge slices through the eyes is the exact failure to avoid.
- If there is no empty region large enough, shrink the type further and use a
  soft translucent gradient rather than an opaque plate, so the photograph still
  reads through it. Never solve it by making the block bigger.
- Aim for editorial restraint: a small, confident block of type on a photograph.
  A heavy band across the middle of the frame is a failure, not a layout.
- Self-contained: no JavaScript, and nothing loaded from anywhere but the fonts
  link above. The only images are background.jpg and any decorative element
  from the library described below.{_decor_rules()}

Explain in `placement_reason` where you put the text and what you avoided."""


class SlideRenderer:
    """Lays a slide out with Claude and screenshots it with Chromium."""

    def __init__(self, client=None):
        # Built lazily: the constructor needs ANTHROPIC_API_KEY. Held on the
        # instance, since an unreferenced client is closed mid-request.
        self._client = client
        self._browsers = asyncio.Semaphore(MAX_BROWSERS)

    def _claude(self):
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SlideError("ANTHROPIC_API_KEY is not set")
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic()
        return self._client

    async def layout(
        self,
        subject: str,
        overlay_text: str,
        background: bytes,
        fmt: CanvasFormat,
        issues: list[str] | None = None,
    ) -> str:
        """The slide as an HTML document, laid out with the background in view."""
        retry_note = ""
        if issues:
            retry_note = (
                "\n\nA previous attempt was rejected for these reasons. Fix them:\n"
                + "\n".join(f"- {i}" for i in issues)
            )
        try:
            response = await self._claude().messages.parse(
                model=LAYOUT_MODEL,
                max_tokens=LAYOUT_MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=_layout_system(),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64.b64encode(background).decode("ascii"),
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"A {fmt.name} slide, {fmt.width}x{fmt.height}px.\n"
                                    f"What the slide is for: {subject}\n"
                                    f"Overlay copy to display verbatim:\n{overlay_text}\n\n"
                                    f"{_layout_rules(fmt)}{retry_note}"
                                ),
                            },
                        ],
                    }
                ],
                output_format=_SlideHTML,
            )
        except SlideError:
            raise
        except Exception as exc:  # noqa: BLE001 -- any SDK or transport failure
            raise SlideError(f"Claude failed: {exc}") from exc
        layout = response.parsed_output
        if layout is None or not layout.html.strip():
            raise SlideError(f"Claude returned no layout (stop_reason={response.stop_reason})")
        return clean_html(layout.html)

    async def screenshot(self, html: str, background: bytes, fmt: CanvasFormat) -> bytes:
        """`html` rendered at the format's size, as a JPEG."""
        from playwright.async_api import async_playwright

        async def serve(route):
            url = urlparse(route.request.url)
            if f"{url.scheme}://{url.netloc}" == PAGE_ORIGIN:
                path = unquote(url.path).lstrip("/")
                if path == "index.html":
                    body, content_type = html.encode("utf-8"), "text/html; charset=utf-8"
                elif path == "background.jpg":
                    body, content_type = background, "image/jpeg"
                elif path.startswith("decor/") and path.count("/") == 2:
                    _, colour, name = path.split("/")
                    body, content_type = tinted_decor(colour, name), "image/png"
                else:
                    body = None
                if body is None:
                    await route.fulfill(status=404)
                else:
                    await route.fulfill(status=200, body=body, content_type=content_type)
            elif url.scheme == "https" and url.hostname in FONT_HOSTS:
                await route.continue_()
            else:
                await route.abort()

        async with self._browsers, async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context(
                    viewport={"width": fmt.width, "height": fmt.height},
                    device_scale_factor=1,
                    # The page is model-written; it gets no scripts of its own.
                    java_script_enabled=False,
                )
                await context.route("**/*", serve)
                page = await context.new_page()
                await page.goto(f"{PAGE_ORIGIN}/index.html", wait_until="networkidle")
                # Webfonts resolve after load; screenshotting early yields fallbacks.
                await page.evaluate("() => document.fonts.ready")
                broken = await page.evaluate(BROKEN_IMAGE_PROBE)
                if broken:
                    # A missing background renders as a blank canvas with a
                    # placeholder icon; the caller lays the slide out again.
                    raise BackgroundMissingError(
                        f"the page references {broken} but it did not load; the background "
                        "must be referenced as 'background.jpg' and decorative elements as "
                        "'decor/<colour>/<file>' with a listed file"
                    )
                return await page.screenshot(
                    type="jpeg",
                    quality=SCREENSHOT_QUALITY,
                    clip={"x": 0, "y": 0, "width": fmt.width, "height": fmt.height},
                )
            except SlideError:
                raise
            except Exception as exc:  # noqa: BLE001 -- any browser failure
                raise SlideError(f"the slide could not be rendered: {exc}") from exc
            finally:
                await browser.close()

    async def render(
        self, subject: str, overlay_text: str, background: bytes, aspect_ratio: str = "9:16"
    ) -> bytes:
        """The finished slide as a JPEG."""
        fmt = FORMATS.get(aspect_ratio)
        if fmt is None:
            raise SlideError(f"aspect ratio must be one of {', '.join(FORMATS)}")
        issues: list[str] = []
        for attempt in range(LAYOUT_RETRIES + 1):
            html = await self.layout(subject, overlay_text, background, fmt, issues)
            try:
                return await self.screenshot(html, background, fmt)
            except BackgroundMissingError as exc:
                if attempt == LAYOUT_RETRIES:
                    raise
                issues = [str(exc)]
        raise AssertionError("unreachable")
