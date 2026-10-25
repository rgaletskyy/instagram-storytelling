"""generate_slide: the user's copy laid out in the brand style over a background photo."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from pydantic import Field

from . import search_api
from .image_generation_service import ImageGenerationError, ImageGenerator
from .slide_html_service import BACKGROUND_MAX_SIDE, SlideError, SlideRenderer

NAME = "generate_slide"
DESCRIPTION = (
    "Invoke this tool when the user asks to generate a slide for a story or a post "
    "carousel: their text laid out in the brand style over a background photo. For "
    "example: 'згенеруй слайд для сторіз використовуючи фото. На фото має бути текст в "
    "брендовому стилі із закликом перейти за посиланням, під ним текст який вказує ціну "
    "продукту'. The slide comes back in the chat as an image."
)

AspectRatio = Literal["9:16", "1:1", "4:5"]

_downloader = ImageGenerator()
_renderer = SlideRenderer()


async def generate_slide(
    subject: Annotated[
        str,
        Field(
            description=(
                "What the slide is for and what should be on it, standalone: rewrite the "
                "user's message so it makes sense without the conversation. Replace pronouns "
                "with the product or topic they refer to, include relevant details mentioned "
                "earlier (dog age, breed, problem, product, promo) and what the user wants "
                "on the slide (objects, text, a call to action), and drop greetings and filler."
            )
        ),
    ],
    backgroundImage: Annotated[
        str,
        Field(
            description=(
                "https link to the photo the slide is laid over, as the user gave it: JPEG, "
                "PNG, WebP or HEIC. Google Drive links work when shared with anyone who has "
                "the link."
            )
        ),
    ],
    overlayText: Annotated[
        str,
        Field(
            description=(
                "The exact text to put on the slide, headline first, in the user's language. "
                "Shown verbatim, so keep it short: a headline and a line or two of body "
                "copy or a call to action."
            )
        ),
    ],
    aspectRatio: Annotated[
        AspectRatio,
        Field(
            description=(
                "'9:16' = full screen, for stories and reels; '4:5' = portrait feed post; "
                "'1:1' = square feed post. '9:16' when not given."
            )
        ),
    ] = "9:16",
) -> ToolResult:
    """Lay out one slide and return it to the chat."""
    if not subject.strip():
        raise ToolError("subject must not be empty")
    if not overlayText.strip():
        raise ToolError("overlayText must not be empty")
    url = backgroundImage.strip()
    search_api.log_call(
        NAME,
        {
            "subject": subject,
            "backgroundImage": url,
            "overlayText": overlayText,
            "aspectRatio": aspectRatio,
        },
    )
    try:
        background = await _downloader.download(url, max_side=BACKGROUND_MAX_SIDE)
        slide = await _renderer.render(subject, overlayText.strip(), background.data, aspectRatio)
    except (ImageGenerationError, SlideError) as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(content=[Image(data=slide, format="jpeg").to_image_content()])
