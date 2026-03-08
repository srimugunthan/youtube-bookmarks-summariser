import asyncio
import random
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors

from youtubesynth.config import settings
from youtubesynth.exceptions import GeminiError


@dataclass
class GeminiResponse:
    text: str
    input_tokens: int
    output_tokens: int


class GeminiClient:
    """Async Gemini wrapper with exponential backoff retry."""

    MAX_RETRIES = 5

    def __init__(self, api_key: str | None = None):
        key = api_key or settings.gemini_api_key
        self._client = genai.Client(api_key=key)

    async def generate(self, model: str, prompt: str) -> GeminiResponse:
        """Call Gemini and return the response.

        Retries on rate-limit (429) and server errors (5xx) with exponential
        backoff + jitter.  Raises GeminiError immediately on 400 bad request.
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                usage = response.usage_metadata
                return GeminiResponse(
                    text=response.text or "",
                    input_tokens=usage.prompt_token_count or 0,
                    output_tokens=usage.candidates_token_count or 0,
                )

            except genai_errors.ClientError as exc:
                # 400 — bad request, no point retrying
                if exc.code == 400:
                    raise GeminiError(f"Invalid request: {exc}") from exc
                # 429 — rate limited, retry with backoff
                last_error = exc

            except genai_errors.ServerError as exc:
                # 5xx — transient server error, retry
                last_error = exc

            # Exponential backoff: 2^attempt seconds + up to 1 s jitter
            delay = (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)

        raise GeminiError(
            f"Gemini call failed after {self.MAX_RETRIES} retries: {last_error}"
        ) from last_error
