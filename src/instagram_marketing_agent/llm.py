"""Model calls: Claude for understanding and writing, Gemini for imagery."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from .config import (
    BODY_MAX_PX,
    CLAUDE_DESCRIBE_MODEL,
    CLAUDE_SCRIPT_MODEL,
    DESIGN_GUIDELINES,
    GEMINI_IMAGE_MODEL,
    GEMINI_TRANSCRIBE_MODEL,
    GOOGLE_FONTS_HREF,
    HEADLINE_MAX_PX,
    LIFESTYLE_BRIEF,
    MAX_LIFESTYLE_IMAGES,
    MAX_SLIDES,
    MIN_SLIDES,
    SIDE_MARGIN,
    STORY_FORMAT,
    STORYTELLING_RULES,
    CanvasFormat,
    load_dotenv,
)
from .models import (
    CampaignScript,
    LifestyleSet,
    LifestyleShot,
    Product,
    SlideSpec,
    SlideVerdict,
)

_anthropic: AsyncAnthropic | None = None
_gemini = None


def anthropic_client() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        load_dotenv()
        _anthropic = AsyncAnthropic()
    return _anthropic


def gemini_client():
    """Built lazily and cached.

    The constructor requires an API key, and the instance must be held: an
    unreferenced client is garbage-collected and closed mid-request.
    """
    global _gemini
    if _gemini is None:
        from google import genai

        load_dotenv()
        _gemini = genai.Client()
    return _gemini


# Slides and frames are generated independently, so unless one person is
# described up front and repeated verbatim, each image invents a different owner
# -- different hands, sleeves and skin on every slide of the same story.
CAST_RULE = (
    "Exactly ONE person appears across this whole set. Describe them once in "
    "`cast`: approximate age, build, skin tone, hands and nails, hair, and "
    "wardrobe (plain and muted -- no patterns, slogans, loud manicure, watches "
    "or jewellery). Do not name them and do not describe a face in detail; they "
    "are mostly hands, forearms and partial figure.\n"
    "Every image that shows a human shows THIS person and no one else. Never a "
    "second person, never a different owner, never a pair of hands belonging to "
    "someone else. Mark `has_human` true on exactly those images."
)


def _cast_check(cast: str) -> str:
    """Tell the reviewer who the one person in this set is meant to be."""
    if not cast.strip():
        return ""
    return (
        f"\nThe only person who may appear anywhere in this set is:\n"
        f"{cast.strip()}\n"
    )


def _cast_failures(cast: str) -> str:
    """Reject a frame that shows the wrong person, or more than one."""
    if not cast.strip():
        return (
            "- more than one person appears, or a stray second pair of hands "
            "enters the frame\n"
        )
    return (
        "- the person shown contradicts the description above (different skin "
        "tone, hands, nails, hair or wardrobe)\n"
        "- more than one person appears, or a stray second pair of hands "
        "enters the frame\n"
    )


def _cast_clause(cast: str) -> str:
    """The line appended to an image prompt so the same person appears."""
    if not cast.strip():
        return ""
    return (
        f"\n\nThe single person in this image is: {cast.strip()}\n"
        "Show only this one person -- one pair of hands, one body. No second "
        "person, no extra hands or arms entering the frame."
    )


class _ScriptDraft(BaseModel):
    """What Opus returns. Products are injected by us, not invented by the model."""

    slides: list[SlideSpec]
    cast: str = ""


class _ImageDescription(BaseModel):
    """A described input asset, flagged if it shows the product packaging."""

    description: str
    shows_product: bool


async def describe_image(image_path: str | Path) -> str:
    """Describe an image in detail with Sonnet."""
    return (await inspect_image(image_path)).description


async def inspect_image(image_path: str | Path) -> _ImageDescription:
    """Describe an image and say whether it shows the product itself.

    The flag is what lets the workflow feed real product photography to image
    generation instead of letting the model invent packaging.
    """
    path = Path(image_path)
    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(path),
                    {
                        "type": "text",
                        "text": (
                            "Describe this image in detail for someone writing an "
                            "Instagram story about it. Cover the subject, setting, "
                            "colours, mood and any product or packaging visible.\n\n"
                            "Set shows_product=true only if a product container "
                            "(bottle, tube, jar, pack) with its own branding is "
                            "clearly visible and usable as a packshot reference."
                        ),
                    },
                ],
            }
        ],
        output_format=_ImageDescription,
    )
    described = response.parsed_output
    if described is None:
        return _ImageDescription(description="", shows_product=False)
    return described


def _rules() -> str:
    return STORYTELLING_RULES.read_text(encoding="utf-8")


def fit_to_count(slides: list[SlideSpec], count: int) -> list[SlideSpec]:
    """Force the script to exactly `count` slides, CTA last.

    The model does not reliably honour the requested length -- it has returned
    six slides for a request of five, with the hook duplicated. Rather than
    trusting it, keep the first slide of each narrative role, top up from any
    repeats, and put the single CTA at the end.
    """
    cta = next((s for s in slides if s.role == "cta"), None)
    rest = [s for s in slides if s is not cta]

    seen: set[str] = set()
    primary: list[SlideSpec] = []
    repeats: list[SlideSpec] = []
    for slide in rest:
        (repeats if slide.role in seen else primary).append(slide)
        seen.add(slide.role)

    room = count - (1 if cta else 0)
    chosen = primary[:room]
    for slide in repeats:
        if len(chosen) >= room:
            break
        chosen.append(slide)
    if cta:
        chosen.append(cta)

    if len(chosen) != count:
        raise ValueError(
            f"the script model returned {len(slides)} usable slides but "
            f"{count} were requested; re-run or choose a different slide count"
        )
    blank = [s.index for s in chosen if not s.overlay_text.strip()]
    if blank:
        raise ValueError(f"slides {blank} have no overlay text")
    return chosen


async def generate_script(
    topic: str,
    descriptions: list[str],
    products: list[Product],
    slide_count: int,
) -> CampaignScript:
    """Write the campaign script with Opus, constrained by the story-telling rules."""
    product_block = "\n\n".join(
        f"SKU {p.sku}\nName: {p.name}\nPrice: {p.price}\nDescription: {p.description}"
        for p in products
    ) or "No product data supplied."

    media_block = "\n\n".join(descriptions) or "No input media supplied."

    system = (
        "You write Instagram story campaigns for the HealthyDoggo brand.\n"
        "The rules below are normative. Follow them exactly.\n\n"
        f"{_rules()}"
    )

    user = (
        f"Topic brief:\n{topic}\n\n"
        f"Products:\n{product_block}\n\n"
        f"Input media descriptions:\n{media_block}\n\n"
        f"Write EXACTLY {slide_count} slides -- not more, not fewer "
        f"({MIN_SLIDES}-{MAX_SLIDES} is the allowed range).\n"
        "Use each narrative role at most once. There is exactly one cta, and it "
        "is the final slide.\n"
        "Write all copy in the same language as the topic brief.\n"
        "For each slide give:\n"
        "  index       - 1-based position\n"
        "  role        - hook | tension | solution | proof | offer | cta\n"
        "  image_prompt- an English prompt for an image model describing the "
        "scene only. Never include a URL, a web address, or any text to "
        "render inside the image.\n"
        "                If the slide features the product, describe the SETTING "
        "and how the product sits in it (surface, light, angle, what is around "
        "it). Do NOT describe the packaging, label, logo or brand name: the real "
        "product photograph is supplied to the image model separately.\n"
        "  shows_product- true when the product container should appear in the "
        "image. Typically the solution, offer and cta slides; usually false for "
        "hook and tension, which are about the problem.\n"
        "  has_human   - true when a hand, arm or person is in frame.\n"
        "  overlay_text- the short copy drawn on the slide, in the brief's "
        "language. REQUIRED on every slide and never empty: a slide with no "
        "words is a dead frame the viewer taps past. Give each slide its own "
        "line of copy -- at minimum a few words. Never leave it blank, never "
        "repeat another slide's copy, and never rely on the image alone to "
        "carry the message.\n"
        "  ig_notes    - stickers, polls or link to add when posting\n"
        "Order the slides hook first and cta last, with exactly one cta.\n\n"
        + CAST_RULE + "\n\n"
        "Before answering, check every slide has non-empty overlay_text."
    )

    response = await anthropic_client().messages.parse(
        model=CLAUDE_SCRIPT_MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=_ScriptDraft,
    )

    draft = response.parsed_output
    if draft is None:
        raise RuntimeError(f"the script model returned no structured output "
                           f"(stop_reason={response.stop_reason})")

    # Trust but verify: the model has returned a slide with no copy at all.
    # Drop wordless slides before fitting so a real one takes the place.
    usable = [
        slide
        for slide in sorted(draft.slides, key=lambda s: s.index)
        if slide.overlay_text.strip() and slide.image_prompt.strip()
    ]
    slides = fit_to_count(usable, slide_count)
    for position, slide in enumerate(slides, start=1):
        slide.index = position

    return CampaignScript(
        topic=topic,
        slides=slides,
        products=products,
        product_url=products[0].product_url if products else None,
        cast=draft.cast,
    )


PRODUCT_FIDELITY_RULE = (
    "The attached photograph shows the REAL product. Reproduce that exact "
    "container in the scene: same shape, proportions, cap, colour and label "
    "artwork. Do not redesign the packaging, do not invent a logo, brand name, "
    "fruit motif or any other label graphic, and do not substitute a different "
    "bottle. Keep the product's own text and markings as they appear in the "
    "photograph. You may relight it and place it naturally in the new scene."
)


async def generate_image(
    prompt: str,
    out_path: str | Path,
    model: str = GEMINI_IMAGE_MODEL,
    references: list[Path] | None = None,
    aspect_ratio: str = STORY_FORMAT.aspect_ratio,
) -> Path:
    """Generate a background at the given aspect. The prompt must never hold a URL.

    When reference photographs are supplied, the real product is composited from
    them rather than imagined -- an image model left to itself invents plausible
    but wrong packaging.
    """
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    text = prompt
    payload: list[dict] = []
    if references:
        text = f"{prompt}\n\n{PRODUCT_FIDELITY_RULE}"
    payload.append({"type": "text", "text": text})
    for reference in references or []:
        payload.append(
            {
                "type": "image",
                "data": base64.b64encode(reference.read_bytes()).decode("utf-8"),
                "mime_type": mimetypes.guess_type(reference.name)[0] or "image/png",
            }
        )

    client = gemini_client()
    interaction = client.interactions.create(
        model=model,
        input=payload if references else text,
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": aspect_ratio,
            "image_size": "2K",
        },
    )
    path.write_bytes(base64.b64decode(interaction.output_image.data))
    return path


async def transcribe_audio(audio_path: str | Path) -> str:
    """Transcribe an audio file.

    Uses gemini-3.5-transcribe rather than the image model named in
    requirements.md, which cannot accept audio input. See research.md R2.
    """
    path = Path(audio_path)
    if not path.exists():
        return ""

    client = gemini_client()
    uploaded = client.files.upload(file=str(path))
    interaction = client.interactions.create(
        model=GEMINI_TRANSCRIBE_MODEL,
        input=[
            {
                "type": "audio",
                "uri": uploaded.uri,
                "mime_type": uploaded.mime_type,
            }
        ],
    )
    return (interaction.output_text or "").strip()


async def revise_slide_spec(slide: SlideSpec, comment: str) -> SlideSpec:
    """Rewrite one slide's prompt and copy from a reviewer's comment."""
    response = await anthropic_client().messages.parse(
        model=CLAUDE_SCRIPT_MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=(
            "You revise a single Instagram story slide. Keep the same index and "
            "role. Never put a URL or web address in image_prompt."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Current slide:\n{slide.model_dump_json(indent=2)}\n\n"
                    f"Reviewer comment:\n{comment}\n\n"
                    "Return the revised slide."
                ),
            }
        ],
        output_format=SlideSpec,
    )
    revised = response.parsed_output
    if revised is None:
        raise RuntimeError("the revision model returned no structured output")
    revised.index = slide.index
    return revised


# --- Slide layout and verification -------------------------------------------


class _SlideHTML(BaseModel):
    """A complete standalone HTML document for one slide."""

    html: str
    placement_reason: str = ""


def _guidelines() -> str:
    return DESIGN_GUIDELINES.read_text(encoding="utf-8")


# Claude's vision API accepts a fixed set of formats and caps each image at
# 5MB. Phone photos are routinely HEIC and well over that, so anything the API
# will not take is converted and downscaled on the way in.
_MAX_IMAGE_BYTES = 4_500_000
_MAX_IMAGE_EDGE = 2000


# Magic bytes, because file extensions lie: a phone export named .png is
# routinely a JPEG, and the API rejects a mismatched media type outright.
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)


def _sniff(raw: bytes) -> str:
    """The real media type of these bytes, or "" when unrecognised."""
    for signature, media_type in _MAGIC:
        if raw.startswith(signature):
            return media_type
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _api_ready(path: Path) -> tuple[bytes, str]:
    """Return image bytes the API will accept, converting or shrinking if needed."""
    raw = path.read_bytes()
    media_type = _sniff(raw)
    if media_type and len(raw) <= _MAX_IMAGE_BYTES:
        return raw, media_type

    import io

    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE), Image.LANCZOS)
        buffer = io.BytesIO()
        im.save(buffer, "JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg"


def _image_block(path: Path) -> dict:
    data, media_type = _api_ready(path)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("utf-8"),
        },
    }


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
- Self-contained: no JavaScript, no images other than background.jpg.

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


async def verify_slide(
    image: Path,
    slide: SlideSpec,
    fmt: CanvasFormat = STORY_FORMAT,
    cast: str = "",
) -> SlideVerdict:
    """Check a rendered slide against the design guidelines and its own copy."""
    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        # Generous: adaptive thinking shares this budget, and a verdict truncated
        # by max_tokens comes back as no verdict at all.
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": (
                    "You review rendered Instagram story slides against the design "
                    "system below. Be strict but fair: report only real, visible "
                    "problems.\n\n" + _guidelines()
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(image),
                    {
                        "type": "text",
                        "text": (
                            f"This is slide {slide.index} (role: {slide.role}).\n"
                            f"It must display this copy:\n{slide.overlay_text}\n"
                            + _cast_check(cast)
                            + "\n"
                            "Judge the WHOLE text block -- the card, panel, "
                            "scrim or gradient behind the copy counts as part "
                            "of it, not just the letters.\n\n"
                            "Fail the slide if any of these is true:\n"
                            "- the text block or its panel covers, touches, or "
                            "cuts across the dog's face, eyes, or the product\n"
                            "- the panel spans the full width edge to edge "
                            "instead of being inset from both sides\n"
                            f"- the text block is taller than about a quarter of "
                            f"the frame ({fmt.text_block_max_h}px of "
                            f"{fmt.height}px)\n"
                            "- an opaque band sits across the middle of the "
                            "image, hiding a large part of the photograph\n"
                            "- text is cut off, overflowing, or overlapping itself\n"
                            f"- text sits outside y={fmt.safe_top}..{fmt.safe_bottom}px\n"
                            "- text is unreadable against the background\n"
                            "- the copy shown differs from the copy above\n"
                            "- the layout looks careless or unbalanced\n"
                            + _cast_failures(cast)
                            + "\n"
                            "Set passed=false with specific, actionable issues, or "
                            "passed=true with an empty issues list."
                        ),
                    },
                ],
            }
        ],
        output_format=SlideVerdict,
    )
    verdict = response.parsed_output
    if verdict is None:
        # Never pass a slide the verifier could not actually judge -- a silent
        # pass would make a broken verifier indistinguishable from a clean run.
        return SlideVerdict(
            index=slide.index,
            passed=False,
            issues=["verifier returned no verdict"],
            notes=f"stop_reason={response.stop_reason}",
        )
    verdict.index = slide.index
    return verdict


# --- Lifestyle content -------------------------------------------------------


def _lifestyle_brief() -> str:
    return LIFESTYLE_BRIEF.read_text(encoding="utf-8")


def _brief_system() -> list[dict]:
    """The lifestyle brief as a cached system prompt."""
    return [
        {
            "type": "text",
            "text": (
                "You are the photographer briefed by the document below. It is "
                "normative: section 10 is an automatic reject list and section "
                "11 is the review checklist.\n\n" + _lifestyle_brief()
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


async def generate_shot_list(
    topic: str,
    product: Product | None,
    packshot: Path | None,
    count: int,
) -> LifestyleSet:
    """Plan a lifestyle set from the brief, with the packshot in view.

    The model sees the real packaging, so scene, palette and lighting are chosen
    from the product rather than guessed -- section 2 of the brief.
    """
    product_block = (
        f"Name: {product.name}\nPrice: {product.price}\n"
        f"Description: {product.description}"
        if product
        else "No catalogue entry; work from the brief and the photograph."
    )

    instructions = (
        f"Plan exactly {count} lifestyle frames "
        f"(1-{MAX_LIFESTYLE_IMAGES} allowed) for this product.\n\n"
        f"PRODUCT_DESCRIPTION:\n{product_block}\n\n"
        f"Creative direction from the requester:\n{topic}\n\n"
        "Follow section 4 for roles. With a small set, prefer distinct roles: "
        "hero first, then in_use or in_hand, then with_dog or detail. Never "
        "repeat a role unless the count exceeds the available roles.\n\n"
        "For each frame write `prompt` in the order section 13 requires: "
        "product and its exact appearance, action, subject, environment, light, "
        "lens and framing, then what to exclude.\n"
        "Do NOT describe the label artwork, brand name or packaging text -- the "
        "real photograph is supplied to the image model, which must reproduce it "
        "unchanged. Refer to it as 'the product shown in the reference photo'.\n"
        "Never ask for text, captions, watermarks or graphic overlays in the "
        "image: section 10 rejects any baked-in text.\n"
        "`excludes` lists what must not appear in that frame.\n\n"
        + CAST_RULE
        + "\nAt least one frame in the set must have has_human=false "
        "(section 13: generated hands are the highest-risk element)."
    )

    response = await anthropic_client().messages.parse(
        model=CLAUDE_SCRIPT_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=_brief_system(),
        messages=[
            {
                "role": "user",
                "content": (
                    [_image_block(packshot), {"type": "text", "text": instructions}]
                    if packshot
                    else instructions
                ),
            }
        ],
        output_format=LifestyleSet,
    )

    planned = response.parsed_output
    if planned is None or not planned.shots:
        raise RuntimeError(
            f"the shot-list model returned nothing "
            f"(stop_reason={response.stop_reason})"
        )

    shots = [s for s in planned.shots if s.prompt.strip()][:count]
    if len(shots) < count:
        raise ValueError(
            f"the shot-list model planned {len(shots)} usable frames but "
            f"{count} were requested"
        )
    for position, shot in enumerate(shots, start=1):
        shot.index = position
    return LifestyleSet(topic=topic, shots=shots)


async def verify_lifestyle_frame(
    image: Path, shot: LifestyleShot, cast: str = ""
) -> SlideVerdict:
    """Judge one frame against the brief's reject list and review checklist."""
    response = await anthropic_client().messages.parse(
        model=CLAUDE_DESCRIBE_MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=_brief_system(),
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(image),
                    {
                        "type": "text",
                        "text": (
                            f"Frame {shot.index} of the set, role: {shot.role}.\n"
                            f"It was shot to this brief:\n{shot.prompt}\n"
                            + _cast_check(cast)
                            + "\n"
                            "Run it against section 10 (automatic reject) and "
                            "section 11 (review checklist). Fail it if any of "
                            "these is true:\n"
                            "- the packaging text or logo is invented, garbled, "
                            "re-typed or mirrored\n"
                            "- the label is hidden, illegible, or turned away\n"
                            "- any text, caption or watermark is baked into the "
                            "image\n"
                            "- hand, paw or dog anatomy is wrong\n"
                            "- the product floats with no contact shadow, or the "
                            "shadow contradicts the light\n"
                            "- a competing brand, unsafe handling, or anything "
                            "toxic to dogs is in frame\n"
                            "- the scene is clinical or implies medical treatment\n"
                            "- scale is implausible\n"
                            + _cast_failures(cast)
                            + "\n"
                            "Set passed=false with specific, actionable issues, "
                            "or passed=true with an empty issues list."
                        ),
                    },
                ],
            }
        ],
        output_format=SlideVerdict,
    )
    verdict = response.parsed_output
    if verdict is None:
        return SlideVerdict(
            index=shot.index,
            passed=False,
            issues=["verifier returned no verdict"],
            notes=f"stop_reason={response.stop_reason}",
        )
    verdict.index = shot.index
    return verdict
