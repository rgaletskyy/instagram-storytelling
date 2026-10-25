"""Image generation with Gemini, from a scene description and reference photographs.

References are fetched by URL (Google Drive share links included), shrunk and
attached to the request, so real products, dogs and scenes are composited
from their photographs rather than imagined: an image model left to itself
invents plausible but wrong packaging.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
IMAGE_SIZE = "2K"
ASPECT_RATIOS = ("9:16", "1:1", "4:5")
# The whole request travels inline, and Gemini caps an inline request at 20 MB.
MAX_REFERENCES = 8
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
REFERENCE_MAX_SIDE = 1536
DOWNLOAD_TIMEOUT = 60.0

SUBJECT_FIDELITY_RULE = (
    "The attached photographs show the REAL subjects of this scene: the product, "
    "the dog, the person, or several of them. Reproduce each one exactly as "
    "photographed.\n"
    "- Product: same container shape, proportions, cap, colour and label "
    "artwork. Do not redesign the packaging, invent a logo, brand name or label "
    "graphic, or substitute a different bottle. Keep its own text and markings "
    "as they appear.\n"
    "  When several product photographs are attached they may be DIFFERENT "
    "products, each with its own label. Reproduce each one from its own "
    "photograph. Do not copy one label onto all of them, and do not add a "
    "product that was not supplied.\n"
    "- Dog: the same individual animal. Same breed, size, coat colour and "
    "markings, same face, same eyes. Do not change the breed or invent a "
    "different dog.\n"
    "- Person: the same individual. Same hands, skin, hair and clothing. One "
    "person only; never add a second.\n"
    "- Scene reference: when a photograph is attached as a sample of the scene, "
    "match its look -- the arrangement, texture, lighting, colour and camera "
    "distance.\n"
    "You may relight the subjects, change their pose and place them naturally in "
    "the new scene. What must not change is who and what they are."
)

_DRIVE_ID = re.compile(r"(?:/d/|[?&]id=)([\w-]{10,})")


class ImageGenerationError(RuntimeError):
    """A reference could not be used, or Gemini produced no image."""


@dataclass(frozen=True)
class Reference:
    """A photograph attached to the request, as JPEG bytes."""

    url: str
    data: bytes
    mime_type: str = "image/jpeg"


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime_type: str = "image/jpeg"


def direct_url(url: str) -> str:
    """A Google Drive share link turned into its download link; any other URL as is."""
    host = urlparse(url).hostname or ""
    if host in ("drive.google.com", "docs.google.com"):
        match = _DRIVE_ID.search(url)
        if match:
            return f"https://drive.usercontent.google.com/download?id={match[1]}&export=download"
    return url


def _shrink(data: bytes) -> bytes:
    """The picture as an RGB JPEG no larger than REFERENCE_MAX_SIDE on its longest side."""
    from PIL import Image, UnidentifiedImageError
    from pillow_heif import register_heif_opener

    register_heif_opener()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageGenerationError("not a readable image") from exc
    image.thumbnail((REFERENCE_MAX_SIDE, REFERENCE_MAX_SIDE))
    if image.mode != "RGB":
        # Transparent cut-outs go on white, not black.
        rgba = image.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


class ImageGenerator:
    """Downloads references and asks Gemini for one image."""

    def __init__(self, client=None, http_transport: httpx.AsyncBaseTransport | None = None):
        # Built lazily: the constructor needs GEMINI_API_KEY. Held on the
        # instance, since an unreferenced client is closed mid-request.
        self._client = client
        self._transport = http_transport

    def _gemini(self):
        if self._client is None:
            if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
                raise ImageGenerationError("GEMINI_API_KEY is not set")
            from google import genai

            self._client = genai.Client()
        return self._client

    async def download(self, url: str) -> Reference:
        """The image at `url`, shrunk for the request."""
        if urlparse(url).scheme != "https":
            raise ImageGenerationError(f"{url}: only https links can be used")
        try:
            async with (
                httpx.AsyncClient(
                    timeout=DOWNLOAD_TIMEOUT, follow_redirects=True, transport=self._transport
                ) as client,
                client.stream("GET", direct_url(url)) as response,
            ):
                if response.status_code != 200:
                    raise ImageGenerationError(f"{url}: download failed ({response.status_code})")
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    raise ImageGenerationError(
                        f"{url}: not an image ({content_type or 'no content type'}); "
                        "a Drive file must be shared with anyone who has the link"
                    )
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_DOWNLOAD_BYTES:
                        raise ImageGenerationError(f"{url}: larger than {MAX_DOWNLOAD_BYTES} bytes")
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"{url}: could not be downloaded: {exc}") from exc
        try:
            return Reference(url=url, data=await asyncio.to_thread(_shrink, bytes(data)))
        except ImageGenerationError as exc:
            raise ImageGenerationError(f"{url}: {exc}") from exc

    async def generate(
        self,
        prompt: str,
        references: Sequence[Reference] = (),
        aspect_ratio: str = "4:5",
    ) -> GeneratedImage:
        """One image of `prompt`, with the subjects of `references` kept as photographed."""
        if aspect_ratio not in ASPECT_RATIOS:
            raise ImageGenerationError(f"aspect ratio must be one of {', '.join(ASPECT_RATIOS)}")
        if len(references) > MAX_REFERENCES:
            raise ImageGenerationError(f"at most {MAX_REFERENCES} reference photographs")

        text = f"{prompt}\n\n{SUBJECT_FIDELITY_RULE}" if references else prompt
        payload: list[dict] = [{"type": "text", "text": text}]
        payload.extend(
            {
                "type": "image",
                "data": base64.b64encode(reference.data).decode("ascii"),
                "mime_type": reference.mime_type,
            }
            for reference in references
        )
        try:
            interaction = await self._gemini().aio.interactions.create(
                model=MODEL,
                input=payload if references else text,
                response_format={
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "aspect_ratio": aspect_ratio,
                    "image_size": IMAGE_SIZE,
                },
            )
        except ImageGenerationError:
            raise
        except Exception as exc:  # noqa: BLE001 -- any SDK or transport failure
            raise ImageGenerationError(f"Gemini failed: {exc}") from exc

        image = getattr(interaction, "output_image", None)
        if image is None or not image.data:
            reason = getattr(interaction, "output_text", None) or "no reason given"
            raise ImageGenerationError(f"Gemini returned no image: {reason}")
        return GeneratedImage(
            data=base64.b64decode(image.data),
            mime_type=getattr(image, "mime_type", None) or "image/jpeg",
        )
