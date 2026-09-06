"""Generating a picture, from a scene description and real photographs."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from ..config import GEMINI_IMAGE_MODEL, STORY_FORMAT
from .base import gemini_client

SUBJECT_FIDELITY_RULE = (
    "The attached photographs show the REAL subjects of this scene: the product, "
    "the dog, the person, or several of them. Reproduce each one exactly as "
    "photographed.\n"
    "- Product: same container shape, proportions, cap, colour and label "
    "artwork. Do not redesign the packaging, invent a logo, brand name or label "
    "graphic, or substitute a different bottle. Keep its own text and markings "
    "as they appear.\n"
    "  When several product photographs are attached they are DIFFERENT "
    "products, each with its own label. Reproduce each one from its own "
    "photograph. Do not copy one label onto all of them, and do not add a "
    "bottle that was not supplied -- the number of products in the scene is the "
    "number of product photographs attached.\n"
    "- Dog: the same individual animal. Same breed, size, coat colour and "
    "markings, same face, same eyes. Do not change the breed or invent a "
    "different dog.\n"
    "- Person: the same individual. Same hands, skin, hair and clothing. One "
    "person only; never add a second.\n"
    "- Scene reference: when a photograph is attached as the scene itself, match "
    "its look -- the same arrangement, texture, lighting, colour and camera "
    "distance. Do not tidy it into a neat grid or a studio render; keep the "
    "irregularity and the reflections of the original.\n"
    "You may relight the subjects, change their pose and place them naturally in "
    "the new scene. What must not change is who and what they are."
)

# Kept for callers that still reference the old name.
PRODUCT_FIDELITY_RULE = SUBJECT_FIDELITY_RULE


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
        text = f"{prompt}\n\n{SUBJECT_FIDELITY_RULE}"
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
