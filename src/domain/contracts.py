"""SearchService data contracts and errors. Mirrors specs/search-service.md.

Fields are snake_case here and camelCase in Firestore, as the collection
schemas in specs/hd-marketing-rag.md name them; the alias bridges the two.
`embeddingText` and `embeddingVector` are stored but never returned.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class InvalidArgument(ValueError):
    """The query is empty."""


class EmbeddingError(RuntimeError):
    """The embedding model or the collection classifier cannot be reached."""


class DataSourceError(RuntimeError):
    """Firestore cannot be accessed."""


class _Document(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    # Cosine distance to the query, from Firestore's distanceResultField: 0 is
    # identical, 2 is opposite. Absent on a document that was not searched for.
    distance: float | None = None


class Product(_Document):
    sku: str
    name: str = ""
    price: float = 0.0
    brand: str = ""
    category: str = ""
    description: str = ""
    volume: str = ""
    weight: str = ""
    size: str = ""


class InstagramMessage(_Document):
    sender: str = ""
    text: str = ""
    timestamp: datetime | None = None


class Content(_Document):
    file_name: str = ""
    drive_url: str = ""
    description: str = ""
    screenshots_path: str = ""
    audio_transcribe: str = ""
    product: str = ""
    brand: str = ""
    breed: str = ""
    tags: str = ""
    type: str = ""
    text_on_image: str = ""
    size_kb: float = 0.0


class SearchResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    products: list[Product] = Field(default_factory=list)
    instagram_messages: list[InstagramMessage] = Field(default_factory=list)
    content: list[Content] = Field(default_factory=list)
