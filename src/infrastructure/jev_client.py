"""TypeSafe's Jev: a typed choice between options, with a probability for each.

POST https://api.typesafe.ai/v1/systemone. A `choice` question answers with
the option picked and a probability for every option; the probabilities sum to
1 across the options.
"""

from __future__ import annotations

import os

import httpx

from domain.contracts import EmbeddingError

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
TIMEOUT = 30.0
# The request's single question is keyed by this id; the answer comes back under it.
QUESTION_ID = "choice"


class JevClient:
    def __init__(self, http: httpx.AsyncClient | None = None, api_key: str | None = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT)
        self._api_key = api_key or os.environ.get(API_KEY_ENV, "")

    async def choice_probabilities(
        self, state: str, instructions: str, options: dict[str, str]
    ) -> dict[str, float]:
        """The probability of each option, keyed as `options` is.

        `options` maps an option's name to what choosing it means. An option
        the answer leaves out has probability 0.
        """
        if not self._api_key:
            raise EmbeddingError(f"{API_KEY_ENV} is not set")
        body = {
            "model": MODEL,
            "state": state,
            "questions": {
                QUESTION_ID: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": options,
                }
            },
        }
        try:
            response = await self._http.post(
                URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
            )
            response.raise_for_status()
            probabilities = response.json()["answers"][QUESTION_ID]["probabilities"]
            return {option: float(probabilities.get(option, 0.0)) for option in options}
        except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise EmbeddingError(f"Jev could not classify the query: {exc}") from exc
