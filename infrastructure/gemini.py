"""The Gemini client. Claude's client and helpers are in anthropic.py."""

from __future__ import annotations

from infrastructure.env import load_dotenv

_gemini = None


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
