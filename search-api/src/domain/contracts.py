"""SearchService data contracts and errors. Mirrors specs/content-search-service.md.

Fields are snake_case here and camelCase in Firestore, as the collection
schemas in specs/marketing-content-rag.md name them; the alias bridges the two.
`embeddingText` and `embeddingVector` are stored but never returned.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class InvalidArgument(ValueError):
    """A parameter is missing or outside the values allowed."""


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
    # The product's main photo on the site: the first of the export's images.
    image_url: str = ""


class InstagramMessage(_Document):
    sender: str = ""
    text: str = ""
    timestamp: datetime | None = None


class InstagramComment(_Document):
    """A comment, or a reply to one, under a post or reel."""

    sender: str = ""
    text: str = ""
    timestamp: datetime | None = None
    # The post or reel the comment was added to.
    parent_id: str = ""


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
    # Derived from `breed` when indexed: Firestore's vector search can only be
    # pre-filtered with equality, and "breed is not empty" is not one.
    has_dog: bool = False


class SearchResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    products: list[Product] = Field(default_factory=list)
    instagram_messages: list[InstagramMessage] = Field(default_factory=list)
    content: list[Content] = Field(default_factory=list)


class MessagingSearchResult(BaseModel):
    """Direct messages (one document per conversation and day) and comments."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    messages: list[InstagramMessage] = Field(default_factory=list)
    comments: list[InstagramComment] = Field(default_factory=list)
    # A period's totals, beyond the documents returned: the conversations active
    # in it, each once, and the comments. None without a period, or for a
    # collection not read.
    total_messages_count: int | None = None
    total_comments_count: int | None = None
