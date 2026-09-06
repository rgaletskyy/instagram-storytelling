"""Writing the campaign script, and revising one slide of it."""

from __future__ import annotations

from pydantic import BaseModel

from ..config import CLAUDE_SCRIPT_MODEL, MAX_SLIDES, MIN_SLIDES
from ..models import CampaignScript, Product, SlideSpec
from .base import CAST_RULE, _rules, anthropic_client


class _ScriptDraft(BaseModel):
    """What Opus returns. Products are injected by us, not invented by the model."""

    slides: list[SlideSpec]
    cast: str = ""



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
        "You write Instagram slide sequences for the HealthyDoggo brand.\n"
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
        "  role        - hook | tension | solution | proof | offer | cta.\n"
        "                These are the field's allowed values. Section 4 of the "
        "rules names the same stages differently -- attention, relevance, "
        "answer, evidence, offer, action -- so map them: attention=hook, "
        "relevance=tension, answer=solution, evidence=proof, offer=offer, "
        "action=cta. Never render a stage name as visible copy.\n"
        "  image_prompt- an English prompt describing the SCENE ONLY: the "
        "setting, the action taking place, the light, the camera angle and "
        "framing, and what to leave out. Never include a URL, a web address, or "
        "any text to render inside the image.\n"
        "                Describe WHAT HAPPENS and WHERE, never WHO or WHAT "
        "things look like. Real photographs of the dog, the person and the "
        "product are attached to the image model, and it copies the subjects "
        "from them. Describing their appearance in words makes it invent a "
        "different dog, a different owner and a fictional label instead.\n"
        "                So: no breed, coat colour, eye colour, size, age, "
        "hair, skin, clothing, packaging or label wording. Refer to them "
        "plainly as 'the dog', 'the owner', 'the product'. Write the pose and "
        "the action freely -- 'the dog sits on a wooden bench scratching behind "
        "its ear, shot at dog level in soft evening light' is right; 'a black "
        "French bulldog with blue eyes' is wrong.\n"
        "  shows_product- true when the product container should appear in the "
        "image. Typically the solution, offer and cta slides; usually false for "
        "hook and tension, which are about the problem.\n"
        "  has_human   - true when a hand, arm or person is in frame.\n"
        "  has_dog     - true when the dog is in frame (usually true).\n"
        "  from_footage- true when the scene recreates something the supplied "
        "video actually shows (a production line, a workshop, a moment from the "
        "clip). A frame is then attached and its look is copied. Set it whenever "
        "the brief asks to use the video, or the scene would otherwise be "
        "imagined from nothing.\n"
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
