"""Slides: laying one out over its background, and judging the result.

Both halves are here because they are two ends of the same job -- the layout
model is told what the reviewer will look for, and the reviewer measures the
same safe area the layout was given.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..config import (
    BODY_MAX_PX,
    CLAUDE_DESCRIBE_MODEL,
    FORMATS,
    GOOGLE_FONTS_HREF,
    HEADLINE_MAX_PX,
    REVIEW_MAX_TOKENS,
    SIDE_MARGIN,
    STORY_FORMAT,
    CanvasFormat,
)
from ..models import ContentFinding, SlideSpec
from .base import _guidelines, _image_block, _rules, anthropic_client


class _SlideHTML(BaseModel):
    """A complete standalone HTML document for one slide."""

    html: str
    placement_reason: str = ""


def _layout_system() -> list[dict]:
    """System prompt with the design guidelines cached across slides."""
    return [
        {
            "type": "text",
            "text": (
                "You lay out Instagram story slides as HTML and CSS for the "
                "HealthyDoggo brand. The design system below is normative.\n\n"
                + _guidelines()
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _decor_rules() -> str:
    """How to use the decorative element library, if it is installed.

    Section 9 of the design guidelines catalogues the assets and section 9's
    own rules govern how many may appear; this only explains the mechanics of
    reaching and recolouring them.
    """
    from ..slide_html import decor_assets

    assets = decor_assets()
    if not assets:
        return ""

    from ..config import DECOR_COLOURS

    return (
        "\n\nDECORATIVE ELEMENTS\n"
        f"The library from section 9 is available: {len(assets)} elements, "
        "already recoloured into the brand palette. Reference one as a plain "
        "image:\n"
        "  <img src=\"decor/turquoise/arrow 1.png\" style=\"position:absolute;"
        "top:340px;left:380px;width:220px\">\n"
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
    decor = _decor_rules()
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
- Self-contained: no JavaScript. The only images are background.jpg and any
  decorative element from the library described below.{decor}

Explain in `placement_reason` where you put the text and what you avoided."""


async def generate_slide_html(
    slide: SlideSpec,
    background: Path,
    issues: list[str] | None = None,
    fmt: CanvasFormat = STORY_FORMAT,
) -> str:
    """Lay a slide out as HTML/CSS, with the background image in view.

    The model sees the actual background, so it can place copy around the
    subject instead of stamping text at a fixed position.
    """
    retry_note = ""
    if issues:
        retry_note = (
            "\n\nA previous attempt was rejected for these reasons. Fix them:\n"
            + "\n".join(f"- {i}" for i in issues)
        )

    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=_layout_system(),
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(background),
                    {
                        "type": "text",
                        "text": (
                            f"Slide {slide.index} of the campaign, role: {slide.role}.\n"
                            f"Overlay copy to display verbatim:\n{slide.overlay_text}\n\n"
                            f"{_layout_rules(fmt)}{retry_note}"
                        ),
                    },
                ],
            }
        ],
        output_format=_SlideHTML,
    )
    layout = response.parsed_output
    if layout is None or not layout.html.strip():
        raise RuntimeError(f"no layout returned for slide {slide.index}")
    return layout.html


class _Findings(BaseModel):
    """The reviewer's output schema. Empty is a legitimate answer."""

    findings: list[ContentFinding] = Field(default_factory=list)


def format_for_image(image: Path) -> CanvasFormat:
    """Pick the artboard from the picture's own proportions.

    Content made by hand arrives as a file and nothing else, so which format it
    is has to be read off the image rather than taken from a caller.
    """
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    with Image.open(image) as im:
        width, height = im.size
    ratio = width / max(height, 1)
    return min(FORMATS.values(), key=lambda f: abs(f.width / f.height - ratio))


def _review_system() -> list[dict]:
    """Both rule documents, cached across every image in one review.

    Byte-identical between the per-image and the sequence pass so the two share
    one cache entry.
    """
    return [
        {
            "type": "text",
            "text": (
                "You review finished Instagram content for the HealthyDoggo "
                "brand against the two normative documents below: the design "
                "system, and the storytelling and scene composition rules. The "
                "work was made by hand by a social media manager, not generated "
                "-- so judge what is there and say how it could be better. Be "
                "strict but fair: report only real problems you can see, and "
                "never invent a finding to fill the list.\n\n"
                "Write every finding in Ukrainian -- both `detail` and `rule` "
                "-- because the people who act on them work in Ukrainian. "
                "`kind` is not prose: it stays exactly 'issue' or "
                "'suggestion'.\n\n"
                + _guidelines()
                + "\n\n"
                + _rules()
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


async def review_content(
    image: Path, description: str, fmt: CanvasFormat
) -> list[ContentFinding]:
    """Judge one finished slide or post against both rule documents.

    The written description comes from the same pass that reads campaign input,
    so the reviewer works from what the picture was already understood to show
    as well as from the picture itself.
    """
    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        # Generous: adaptive thinking shares this budget, and a review truncated
        # by max_tokens comes back as no review at all.
        max_tokens=REVIEW_MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_review_system(),
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(image),
                    {
                        "type": "text",
                        "text": (
                            f"{image.name} -- a finished {fmt.name} piece, "
                            f"{fmt.width}x{fmt.height}px.\n\n"
                            f"Read as: {description}\n\n"
                            "Report what is wrong and what would make it "
                            "stronger. Cover at least:\n"
                            f"- the text-safe area: copy inside "
                            f"y={fmt.safe_top}..{fmt.safe_bottom}px "
                            f"({fmt.safe_note})\n"
                            "- the whole text block, including the card, plate, "
                            "scrim or gradient behind the copy: inset from both "
                            "sides rather than edge to edge, and no taller than "
                            f"about {fmt.text_block_max_h}px of {fmt.height}px\n"
                            "- whether that block covers a dog's face or eyes, "
                            "or the product\n"
                            "- text cut off, overflowing, overlapping itself, "
                            "or unreadable against what sits behind it\n"
                            "- one clear focal point; photography, colour, type "
                            "and decorative elements against the brand "
                            "foundations\n"
                            "- the copy: concise, one language, addressed to "
                            "one person, doing one job on this slide\n"
                            "- anything the do/don't and QA checklists reject\n\n"
                            "Judge only this image. Leave anything that needs "
                            "the rest of the set -- sequence structure, whether "
                            "the arc works -- to the pass that sees them all.\n\n"
                            "kind='issue' for a breach of the documents, "
                            "kind='suggestion' for something that breaks no rule "
                            "but would land better. Name the section in `rule`. "
                            "One specific, actionable sentence per finding, "
                            "saying what and where. Return nothing for content "
                            "that is already right."
                        ),
                    },
                ],
            }
        ],
        output_format=_Findings,
    )
    review = response.parsed_output
    if review is None:
        # An empty list would make a review that never happened look like a
        # clean bill of health.
        return [
            ContentFinding(
                kind="issue",
                detail=(
                    f"{image.name} could not be reviewed: the reviewer returned "
                    f"nothing (stop_reason={response.stop_reason})"
                ),
            )
        ]
    return [f for f in review.findings if f.detail.strip()]


async def review_content_sequence(descriptions: list[str]) -> list[ContentFinding]:
    """Judge a set read in order, on what one frame cannot show.

    Descriptions rather than the images: the sequence rules are about what the
    slides say and in what order, which the written reading already carries.
    """
    numbered = "\n\n".join(
        f"Slide {i}: {text}" for i, text in enumerate(descriptions, 1)
    )
    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        max_tokens=REVIEW_MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_review_system(),
        messages=[
            {
                "role": "user",
                "content": (
                    f"These {len(descriptions)} pieces are one sequence, in "
                    f"filename order:\n\n{numbered}\n\n"
                    "Judge only what the set as a whole shows: one main idea "
                    "across the sequence, one communication job per slide, an "
                    "opening that earns the next tap, forward momentum, a single "
                    "clear final action, and the same protagonist throughout.\n\n"
                    "kind='issue' for a breach of the sequence rules, "
                    "kind='suggestion' for an improvement. Name the section in "
                    "`rule`. Say which slide each finding is about. Return "
                    "nothing if the sequence holds."
                ),
            }
        ],
        output_format=_Findings,
    )
    review = response.parsed_output
    if review is None:
        return [
            ContentFinding(
                kind="issue",
                detail=(
                    "the set could not be reviewed as a sequence: the reviewer "
                    f"returned nothing (stop_reason={response.stop_reason})"
                ),
            )
        ]
    return [f for f in review.findings if f.detail.strip()]
