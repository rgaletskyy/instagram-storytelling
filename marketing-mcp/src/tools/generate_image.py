"""generate_image: a new image from the user's scene description, product photos and samples."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from pydantic import Field

from . import search_api
from .image_generation_service import (
    MAX_REFERENCES,
    ImageGenerationError,
    ImageGenerator,
    Reference,
)

NAME = "generate_image"
DESCRIPTION = (
    "Invoke this tool when the user asks to generate an image from a description of the "
    "scene and the elements that should be in it. For example: 'собака сидить біля баночки "
    "з вітамінами', 'собака сидить у ванні, рука тримає шампунь Sensitive Skin біля "
    "мордочки собаки'. Products named in `products` are drawn from their real photographs "
    "in the content library; photos at `sampleUrls` are attached as references too. "
    "The image comes back in the chat."
)

ContentType = Literal["Product photo", "Lifestyle", "Studio photoshoot", "UGC"]
Composition = Literal["Centered", "Rule of Thirds", "Flat Lay", "Close-up", "Wide"]
CameraLevel = Literal["Eye Level", "High Angle", "Top-Down", "Low Angle", "Ground Level"]
AspectRatio = Literal["9:16", "1:1", "4:5"]

CONTENT_TYPE_PROMPTS = {
    "Product photo": "A clean product photograph that shows the product clearly.",
    "Lifestyle": "A natural lifestyle photograph of everyday life with a dog, as on Instagram.",
    "Studio photoshoot": "A professional studio photoshoot with controlled lighting and a plain backdrop.",
    "UGC": "An authentic user-generated phone photo: casual, unpolished, natural light.",
}
COMPOSITION_PROMPTS = {
    "Centered": "Main subject centred in the frame.",
    "Rule of Thirds": "Main subject placed on a rule-of-thirds line.",
    "Flat Lay": "Flat lay: objects arranged on a surface, shot from directly above.",
    "Close-up": "Close-up: the subject fills most of the frame.",
    "Wide": "Wide shot: the subject with plenty of surrounding scene.",
}
CAMERA_PROMPTS = {
    "Eye Level": "Camera at eye level with the subject.",
    "High Angle": "Camera above the subject, looking down at an angle.",
    "Top-Down": "Camera directly above, looking straight down.",
    "Low Angle": "Camera below the subject, looking up.",
    "Ground Level": "Camera on the ground, at the dog's level.",
}

# Product photos in the content library: indexed with this type, linked to a
# product by its name in `product`.
PRODUCT_CONTENT_TYPE = "продуктове"
PHOTOS_PER_PRODUCT = 2
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic")

_generator = ImageGenerator()


def _matches(product_name: str, labelled: str) -> bool:
    a, b = product_name.casefold().strip(), labelled.casefold().strip()
    return bool(a and b) and (a in b or b in a)


async def _search(body: dict[str, Any]) -> dict[str, Any]:
    result = await search_api.post("/searchcontent", body)
    return result if isinstance(result, dict) else {}


async def product_photo_urls(product: str) -> tuple[str, list[str]]:
    """The product's name and the links of up to PHOTOS_PER_PRODUCT of its photos.

    `product` is a SKU or a name. A SKU is resolved to the product's name
    first, since photos are labelled by name; a name passes through.
    """
    found = await _search({"query": product, "productSku": product, "type": PRODUCT_CONTENT_TYPE})
    name = product
    for item in found.get("products") or []:
        if str(item.get("sku", "")).casefold() == product.casefold() and item.get("name"):
            name = item["name"]
            # The first search ranked content by the SKU's wording; rank by the name.
            found = await _search({"query": name, "type": PRODUCT_CONTENT_TYPE})
            break

    urls = [
        item["driveUrl"]
        for item in found.get("content") or []
        if item.get("driveUrl")
        and _matches(name, item.get("product", ""))
        and item.get("fileName", "").casefold().endswith(IMAGE_EXTENSIONS)
    ]
    return name, urls[:PHOTOS_PER_PRODUCT]


def build_prompt(
    subject: str,
    product_names: list[str],
    content_type: str | None,
    composition: str | None,
    camera_level: str | None,
    with_samples: bool,
) -> str:
    lines = [subject.strip()]
    if content_type:
        lines.append(CONTENT_TYPE_PROMPTS[content_type])
    if composition:
        lines.append(COMPOSITION_PROMPTS[composition])
    if camera_level:
        lines.append(CAMERA_PROMPTS[camera_level])
    if product_names:
        lines.append(
            "Products in the scene, from the attached product photographs: "
            + ", ".join(product_names)
            + "."
        )
    if with_samples:
        lines.append("Sample photographs of the desired look are attached as well.")
    lines.append("No text, captions, watermarks or logos other than those on the products.")
    return "\n".join(lines)


async def generate_image(
    subject: Annotated[
        str,
        Field(
            description=(
                "What the image shows, standalone: rewrite the user's message so it makes "
                "sense without the conversation. Replace pronouns with the product or "
                "topic they refer to, keep every detail of the scene the user gave (dog "
                "breed, age, pose, place, props, hands, mood, lighting) and drop greetings "
                "and filler."
            )
        ),
    ],
    products: Annotated[
        list[str] | None,
        Field(
            description=(
                "Products that must appear in the image, one entry each: the exact SKU when "
                "the conversation has it, otherwise the product name as the user wrote it "
                "(e.g. 'Sensitive Skin shampoo'). Leave empty when no product is named."
            )
        ),
    ] = None,
    contentType: Annotated[
        ContentType | None,
        Field(
            description=(
                "Kind of picture. 'Product photo' = the product is the hero; 'Lifestyle' = "
                "everyday life with a dog; 'Studio photoshoot' = studio light and backdrop; "
                "'UGC' = a casual phone photo by a customer. Leave empty if unclear."
            )
        ),
    ] = None,
    composition: Annotated[
        Composition | None,
        Field(
            description=(
                "How the elements are placed and framed: 'Centered', 'Rule of Thirds', "
                "'Flat Lay' (laid out on a surface, seen from above), 'Close-up' or 'Wide'. "
                "Leave empty if the user did not say."
            )
        ),
    ] = None,
    cameraLevel: Annotated[
        CameraLevel | None,
        Field(
            description=(
                "Where the camera is relative to the subject: 'Eye Level', 'High Angle' "
                "(above, looking down), 'Top-Down' (straight down), 'Low Angle' (below, "
                "looking up) or 'Ground Level' (at the dog's level). Leave empty if the "
                "user did not say."
            )
        ),
    ] = None,
    aspectRatio: Annotated[
        AspectRatio,
        Field(
            description=(
                "'9:16' = full screen, for stories and reels; '4:5' = portrait feed post; "
                "'1:1' = square feed post. A post without a stated shape is '4:5'."
            )
        ),
    ] = "4:5",
    sampleUrls: Annotated[
        list[str] | None,
        Field(
            description=(
                "https links to sample images the new image must follow (a dog, a scene, a "
                "style), as the user gave them: JPEG, PNG, WebP or HEIC. Google Drive "
                "links work when shared with anyone who has the link."
            )
        ),
    ] = None,
) -> ToolResult:
    """Generate one image and return it to the chat."""
    if not subject.strip():
        raise ToolError("subject must not be empty")
    wanted = [p.strip() for p in products or [] if p.strip()]
    samples = [u.strip() for u in sampleUrls or [] if u.strip()]
    search_api.log_call(
        NAME,
        {
            "subject": subject,
            "products": wanted,
            "contentType": contentType,
            "composition": composition,
            "cameraLevel": cameraLevel,
            "aspectRatio": aspectRatio,
            "sampleUrls": samples,
        },
    )

    notes: list[str] = []
    found = await asyncio.gather(*(product_photo_urls(p) for p in wanted))
    product_names = [name for name, _ in found]
    product_urls = [url for _, urls in found for url in urls]
    for (name, urls), asked in zip(found, wanted, strict=True):
        if not urls:
            notes.append(f"No photo of '{asked}' was found; it was drawn from its name only.")
        elif name != asked:
            notes.append(f"'{asked}' is {name}.")

    if len(samples) > MAX_REFERENCES:
        raise ToolError(f"at most {MAX_REFERENCES} sample links")
    room = MAX_REFERENCES - len(samples)
    if len(product_urls) > room:
        notes.append(f"Only {room} product photos were attached, to stay within the limit.")
        product_urls = product_urls[:room]

    async def fetch(url: str) -> Reference | None:
        try:
            return await _generator.download(url)
        except ImageGenerationError as exc:
            notes.append(f"A product photo was skipped: {exc}")
            return None

    try:
        # A sample the user gave must be used, so its failure fails the call;
        # a product photo found by search is skipped instead.
        sample_refs = await asyncio.gather(*(_generator.download(u) for u in samples))
        product_refs = await asyncio.gather(*(fetch(u) for u in product_urls))
        references = [r for r in product_refs if r] + list(sample_refs)
        prompt = build_prompt(
            subject, product_names, contentType, composition, cameraLevel, bool(samples)
        )
        image = await _generator.generate(prompt, references, aspectRatio)
    except ImageGenerationError as exc:
        raise ToolError(str(exc)) from exc

    content: list[Any] = [
        Image(data=image.data, format=image.mime_type.split("/")[-1]).to_image_content()
    ]
    if notes:
        content.append("\n".join(notes))
    return ToolResult(content=content)
