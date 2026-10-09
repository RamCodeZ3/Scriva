from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from domain.exceptions import DocumentBuildError

from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
)


class OpenAICompatibleDocumentWriterAdapter(GeminiDocumentWriterAdapter):
    """Document writer for OpenAI-compatible chat completion APIs.

    Prompt construction and response interpretation are intentionally inherited
    from the canonical Scriva writer so every provider receives the same rules.
    """

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        model_name: str,
        max_input_tokens: int,
    ) -> None:
        self.provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self.max_input_tokens = max_input_tokens

    async def _generate(self, prompt: str, *, system_instruction: str) -> str:
        return await asyncio.to_thread(
            self._generate_sync, prompt, system_instruction
        )

    def _generate_sync(self, prompt: str, system_instruction: str) -> str:
        payload = json.dumps(
            {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            }
        ).encode()
        request = Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request) as response:  # noqa: S310
                data = json.loads(response.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise DocumentBuildError(
                f"{self.provider_name} HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, OSError, ValueError) as exc:
            raise DocumentBuildError(
                f"{self.provider_name} request failed: {exc}"
            ) from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DocumentBuildError(
                f"{self.provider_name} returned an invalid response."
            ) from exc
