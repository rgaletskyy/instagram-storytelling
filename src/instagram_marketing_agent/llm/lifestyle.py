"""Lifestyle sets: planning the shot list, and judging each frame against it."""

from __future__ import annotations

from pathlib import Path

from ..config import (
    CLAUDE_DESCRIBE_MODEL,
    CLAUDE_SCRIPT_MODEL,
    LIFESTYLE_BRIEF,
    MAX_LIFESTYLE_IMAGES,
)
from ..models import LifestyleSet, LifestyleShot, Product, SlideVerdict
from .base import CAST_RULE, _cast_check, _cast_failures, _image_block, anthropic_client


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
