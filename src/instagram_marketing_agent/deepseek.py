"""DeepSeek's vision model, over its OpenAI-compatible chat endpoint.

Reached only when config.DESCRIBE_MODEL names a DeepSeek model. One endpoint
and one request shape, so it goes over httpx -- already a dependency -- rather
than pulling in a second SDK for a single call.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from .config import DEEPSEEK_BASE_URL, DEEPSEEK_KEY_ENV, load_dotenv

# Describing a photograph is a single long call, not a chat turn; the default
# five seconds times out on a large image.
_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


def api_key() -> str:
    """The DeepSeek key, with an error that says which setting asked for it."""
    load_dotenv()
    key = os.environ.get(DEEPSEEK_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"{DEEPSEEK_KEY_ENV} is not set, but DESCRIBE_MODEL names a DeepSeek "
            f"model. Add the key to .env, or set DESCRIBE_MODEL back to a Claude model."
        )
    return key


def _json_object(text: str, model: str) -> dict[str, Any]:
    """Pull the JSON object out of a reply.

    DeepSeek documents JSON output for its text models only and warns that the
    content can come back empty, so the reply is unwrapped rather than trusted:
    a fenced block or a sentence of preamble around the object still parses.
    """
    body = text.strip()
    if body.startswith("```"):
        body = body.partition("\n")[2].rpartition("```")[0]
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        body = body[start : end + 1]
    try:
        parsed = json.loads(body)
    except ValueError as exc:
        raise RuntimeError(
            f"{model} did not return JSON: {text.strip()[:300] or '(empty reply)'}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{model} returned {type(parsed).__name__}, not a JSON object")
    return parsed


async def describe_json(
    model: str,
    image: bytes,
    media_type: str,
    prompt: str,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Send one image with a prompt and return the JSON object it asked for.

    The image travels as a data URI: the alternatives are a public https URL or
    an upload to their Files API, and the photographs here are local.
    """
    data_uri = f"data:{media_type};base64,{base64.standard_b64encode(image).decode()}"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri, "detail": "auto"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}"},
            json=payload,
        )

    if response.status_code >= 400:
        # The body carries the reason -- an unknown model id, an expired key --
        # and raise_for_status throws it away.
        raise RuntimeError(
            f"DeepSeek returned {response.status_code} for {model}: "
            f"{response.text.strip()[:400]}"
        )

    choices = response.json().get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    return _json_object(content or "", model)
