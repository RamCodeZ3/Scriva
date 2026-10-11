from __future__ import annotations

import os

from domain.exceptions import DocumentBuildError
from groq import AsyncGroq

from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
)


class GroqDocumentWriterAdapter(GeminiDocumentWriterAdapter):
    """Document writer backed by Groq's asynchronous chat completions API.

    Prompt construction and response interpretation are inherited from the
    canonical Scriva writer so both configured providers follow the same
    document rules.
    """

    provider_name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        max_input_tokens: int,
        base_url: str | None = None,
        client: AsyncGroq | None = None,
    ) -> None:
        configured_base_url = base_url or os.environ.get("GROQ_BASE_URL")
        normalized_base_url = _normalize_base_url(configured_base_url)
        self._client = client or AsyncGroq(
            api_key=api_key,
            base_url=normalized_base_url,
        )
        self._model_name = model_name
        self.max_input_tokens = max_input_tokens

    async def _generate(self, prompt: str, *, system_instruction: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise DocumentBuildError(f"Groq request failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise DocumentBuildError("Groq returned an empty response.")
        return content


def _normalize_base_url(base_url: str | None) -> str:
    value = (base_url or "https://api.groq.com").rstrip("/")
    return value.removesuffix("/openai/v1").rstrip("/")
