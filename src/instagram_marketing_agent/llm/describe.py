"""Reading the input media: what a photograph shows, and what a clip says."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ..config import (
    DEEPSEEK_MODEL_PREFIX,
    DESCRIBE_MODEL,
    GEMINI_TRANSCRIBE_MODEL,
)
from .base import _api_ready, _image_block, anthropic_client, gemini_client


class _ImageDescription(BaseModel):
    """A described input asset, flagged by what it can serve as a reference for.

    The flags decide which real photograph is attached when a slide featuring
    that subject is generated, so the dog and the owner are reproduced rather
    than reinvented from a written description.
    """

    description: str
    shows_product: bool
    shows_dog: bool = False
    shows_person: bool = False


# Asked of whichever model config.DESCRIBE_MODEL names, so both providers are
# judging the photograph against the same brief.
_INSPECT_INSTRUCTIONS = (
    "Describe this image in detail for someone writing an "
    "Instagram story about it. Cover the subject, setting, "
    "colours, mood and any product or packaging visible.\n\n"
    "Then flag what this photo could serve as a "
    "reference for, judging only whether the subject is "
    "clear enough to copy from:\n"
    "  shows_product - a product container (bottle, tube, "
    "jar, pack) with its own branding is clearly visible\n"
    "  shows_dog     - a dog is clearly visible, its face "
    "and coat legible\n"
    "  shows_person  - a person is visible: hands, arms, "
    "or body"
)

# DeepSeek has no typed-output API, so the shape is spelled out in the prompt.
# Their JSON mode also requires the word "json" to appear in it.
_INSPECT_JSON_SHAPE = (
    "\n\nReply with one json object and nothing else, in exactly this shape:\n"
    '{"description": "...", "shows_product": true, "shows_dog": false, '
    '"shows_person": false}'
)


async def describe_image(image_path: str | Path) -> str:
    """Describe an image in detail with the configured description model."""
    return (await inspect_image(image_path)).description


async def inspect_image(image_path: str | Path) -> _ImageDescription:
    """Describe an image and say whether it shows the product itself.

    The flag is what lets the workflow feed real product photography to image
    generation instead of letting the model invent packaging.
    """
    path = Path(image_path)
    if DESCRIBE_MODEL.startswith(DEEPSEEK_MODEL_PREFIX):
        return await _inspect_with_deepseek(path)
    response = await anthropic_client().messages.parse(
        model=DESCRIBE_MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(path),
                    {"type": "text", "text": _INSPECT_INSTRUCTIONS},
                ],
            }
        ],
        output_format=_ImageDescription,
    )
    described = response.parsed_output
    if described is None:
        return _ImageDescription(description="", shows_product=False)
    return described


async def _inspect_with_deepseek(path: Path) -> _ImageDescription:
    """The same inspection, run on a DeepSeek vision model.

    An unusable reply is raised rather than downgraded to a bare description:
    the flags decide which real photograph is attached when the product is
    generated, and losing them quietly puts an invented label on the packaging.
    """
    from .deepseek import describe_json

    data, media_type = _api_ready(path)
    payload = await describe_json(
        model=DESCRIBE_MODEL,
        image=data,
        media_type=media_type,
        prompt=_INSPECT_INSTRUCTIONS + _INSPECT_JSON_SHAPE,
    )
    description = str(payload.get("description") or "").strip()
    if not description:
        raise RuntimeError(f"{DESCRIBE_MODEL} returned no description for {path.name}")
    return _ImageDescription(
        description=description,
        shows_product=bool(payload.get("shows_product")),
        shows_dog=bool(payload.get("shows_dog")),
        shows_person=bool(payload.get("shows_person")),
    )


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
