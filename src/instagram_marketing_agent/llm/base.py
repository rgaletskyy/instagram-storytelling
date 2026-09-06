"""What every model call needs: the clients, the rule documents, the images.

Kept apart from the calls themselves so slides.py and lifestyle.py can share it
without importing each other.
"""

from __future__ import annotations

import base64
from pathlib import Path

from anthropic import AsyncAnthropic

from ..config import DESIGN_GUIDELINES, STORYTELLING_RULES, load_dotenv

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
    "Exactly ONE person appears anywhere in this set, and one dog. Never a "
    "second person, never a different owner, never a stray extra pair of hands, "
    "never a different animal.\n"
    "Do NOT describe what they look like, here or in any image_prompt. Their "
    "appearance comes from the attached reference photographs, not from words. "
    "In `cast`, record only how the person appears in frame across the set -- "
    "for example 'mostly hands and forearms, one partial figure' -- and nothing "
    "about their face, hair, skin or clothing.\n"
    "Mark `has_human` true on exactly the images that show a person."
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
    """The framing note appended when a person is in the image.

    Deliberately carries no appearance: who the person is comes from the
    attached photograph. Describing them in words is what makes the model
    invent someone new on each slide.
    """
    note = (
        "\n\nExactly one person is in this image -- one pair of hands, one "
        "body, the same person as in the attached photograph. No second person, "
        "no extra hands or arms entering the frame."
    )
    if cast.strip():
        note += f"\nHow they appear in frame: {cast.strip()}"
    return note


def _rules() -> str:
    return STORYTELLING_RULES.read_text(encoding="utf-8")


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
