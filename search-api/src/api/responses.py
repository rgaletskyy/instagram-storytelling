"""Response shaping shared by the endpoints."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel


def without_empty(endpoint: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Answer with the endpoint's result minus every empty property, at any depth.

    Put it under the route decorator. The route's `response_model` still
    documents the full shape; the answer leaves out what is empty, so a
    missing property means "no value". List items are kept, only emptied.
    """

    @functools.wraps(endpoint)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await endpoint(*args, **kwargs)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json", by_alias=True)
        return JSONResponse(prune(result))

    return wrapper


def prune(value: Any) -> Any:
    """`value` with the empty properties of its objects removed, recursively."""
    if isinstance(value, dict):
        pruned = {key: prune(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if not _is_empty(item)}
    if isinstance(value, list):
        return [prune(item) for item in value]
    return value


def _is_empty(value: Any) -> bool:
    """No value, an empty string, list or object. 0 and false are values."""
    return value is None or (isinstance(value, str | list | dict) and not value)
