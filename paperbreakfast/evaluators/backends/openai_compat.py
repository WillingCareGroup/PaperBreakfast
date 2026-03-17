"""
OpenAI-compatible backend.

Works with any server exposing a /v1/chat/completions endpoint:
  - LM Studio  (default: http://localhost:1234/v1)
  - Ollama     (default: http://localhost:11434/v1)
  - vLLM, LocalAI, etc.

The api_key is required by the openai SDK but local servers accept any non-empty string.
"""
from openai import OpenAI, OpenAIError

from paperbreakfast.evaluators.base import BackendError, LLMBackend


class OpenAICompatBackend(LLMBackend):

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "local",
        model: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 512,
    ):
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._base_url = base_url

    @property
    def name(self) -> str:
        host = self._base_url.replace("http://", "").replace("https://", "").split("/")[0]
        return f"openai_compat:{host}/{self._model}"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return response.choices[0].message.content or ""
        except OpenAIError as e:
            raise BackendError(
                f"OpenAI-compat error at {self._base_url}: {e}\n"
                "Make sure your local server is running."
            ) from e
        except Exception as e:
            raise BackendError(f"Unexpected error calling {self._base_url}: {e}") from e
