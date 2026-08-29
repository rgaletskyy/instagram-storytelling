"""Pydantic entities. Mirrors specs/001-instagram-story-agent/data-model.md."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import MAX_SLIDES, MIN_SLIDES

SlideRole = Literal["hook", "tension", "solution", "proof", "offer", "cta"]


class Product(BaseModel):
    """A row from src/resources/products.xlsx."""

    sku: str
    name: str
    price: str = ""
    image_url: str = ""
    product_url: str = ""
    description: str = ""


class SlideSpec(BaseModel):
    """One slide of the generated script."""

    index: int
    role: SlideRole
    image_prompt: str
    overlay_text: str
    ig_notes: str = ""
    shows_product: bool = False


class CampaignScript(BaseModel):
    """The whole generated script; also the structured-output schema for Opus."""

    topic: str
    slides: list[SlideSpec]
    products: list[Product] = Field(default_factory=list)
    product_url: str | None = None

    @field_validator("slides")
    @classmethod
    def _check_length(cls, slides: list[SlideSpec]) -> list[SlideSpec]:
        if not MIN_SLIDES <= len(slides) <= MAX_SLIDES:
            raise ValueError(
                f"a story must have {MIN_SLIDES}-{MAX_SLIDES} slides, got {len(slides)}"
            )
        return slides


class SlideVerdict(BaseModel):
    """The verifier's judgement on one rendered slide."""

    index: int = 0
    passed: bool
    issues: list[str] = Field(default_factory=list)
    notes: str = ""


ShotRole = Literal["hero", "in_hand", "in_use", "with_dog", "detail", "flat_lay"]


class LifestyleShot(BaseModel):
    """One frame of a lifestyle set. Section 4 of the lifestyle brief."""

    index: int
    role: ShotRole
    prompt: str
    excludes: str = ""
    has_human: bool = False


class LifestyleSet(BaseModel):
    """The shot list for one product."""

    topic: str
    shots: list[LifestyleShot]


class LifestyleFrame(BaseModel):
    """A rendered frame and how it was judged."""

    index: int
    role: ShotRole
    path: Path
    verdict: SlideVerdict | None = None


class MediaDescription(BaseModel):
    """An input asset and the description derived from it."""

    path: Path
    kind: Literal["image", "video"]
    description: str
    transcript: str | None = None
    shows_product: bool = False

    def as_context(self) -> str:
        text = f"{self.path.name}: {self.description}"
        if self.transcript:
            text += f"\nSpoken content: {self.transcript}"
        return text


class Campaign(BaseModel):
    """The result of one run."""

    topic: str
    script: CampaignScript
    slide_paths: list[Path] = Field(default_factory=list)
    output_dir: Path | None = None
    missing_skus: list[str] = Field(default_factory=list)
    failed_slides: list[tuple[int, str]] = Field(default_factory=list)
    verdicts: list[SlideVerdict] = Field(default_factory=list)
    product_references: list[Path] = Field(default_factory=list)
    format_name: str = "story"
