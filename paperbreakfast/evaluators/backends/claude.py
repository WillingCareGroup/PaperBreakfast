import anthropic

from paperbreakfast.evaluators.base import BackendError, LLMBackend


class ClaudeBackend(LLMBackend):

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.1,
        max_tokens: int = 512,
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
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except anthropic.AuthenticationError as e:
            raise BackendError(f"Claude authentication failed: {e}") from e
        except anthropic.RateLimitError as e:
            raise BackendError(f"Claude rate limit: {e}") from e
        except anthropic.APIError as e:
            raise BackendError(f"Claude API error: {e}") from e
