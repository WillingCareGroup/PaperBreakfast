import logging
import time

import anthropic

from paperbreakfast.evaluators.base import BackendError, LLMBackend

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; doubled each attempt (2s, 4s, 8s)


class ClaudeBackend(LLMBackend):

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        if not api_key:
            raise BackendError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return f"claude:{self._model}"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # AuthenticationError is permanent — fail immediately, no retry.
        # RateLimitError and transient APIErrors are retried with exponential backoff.
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                message = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    system=[{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{"role": "user", "content": user_prompt}],
                )
                if not message.content:
                    logger.warning(
                        f"Claude returned empty content (stop_reason={message.stop_reason})"
                    )
                    return ""
                return message.content[0].text

            except anthropic.AuthenticationError as e:
                raise BackendError(f"Claude authentication failed: {e}") from e

            except (anthropic.RateLimitError, anthropic.APIError) as e:
                last_exc = e
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Claude transient error (attempt {attempt + 1}/{_MAX_RETRIES}), "
                        f"retrying in {delay:.0f}s: {e}"
                    )
                    time.sleep(delay)

        raise BackendError(
            f"Claude API error after {_MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc
