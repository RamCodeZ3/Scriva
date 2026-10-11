from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from domain.exceptions import DocumentBuildError
from infrastructure.ai.groq_document_writer_adapter import (
    GroqDocumentWriterAdapter,
)


class GroqDocumentWriterAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock())
            )
        )
        self.adapter = GroqDocumentWriterAdapter(
            api_key="test-key",
            model_name="openai/gpt-oss-120b",
            max_input_tokens=128_000,
            client=self.client,
        )

    async def test_generates_json_with_async_groq_client(self) -> None:
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"title": "Test"}')
                )
            ]
        )

        result = await self.adapter._generate(
            "source prompt",
            system_instruction="system rules",
        )

        self.assertEqual(result, '{"title": "Test"}')
        self.client.chat.completions.create.assert_awaited_once_with(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": "system rules"},
                {"role": "user", "content": "source prompt"},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

    async def test_translates_sdk_failure(self) -> None:
        self.client.chat.completions.create.side_effect = RuntimeError(
            "HTTP 429"
        )

        with self.assertRaisesRegex(DocumentBuildError, "HTTP 429"):
            await self.adapter._generate(
                "source prompt",
                system_instruction="system rules",
            )

    async def test_rejects_empty_response(self) -> None:
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )

        with self.assertRaisesRegex(DocumentBuildError, "empty response"):
            await self.adapter._generate(
                "source prompt",
                system_instruction="system rules",
            )

    def test_normalizes_openai_compatible_base_url(self) -> None:
        with patch(
            "infrastructure.ai.groq_document_writer_adapter.AsyncGroq"
        ) as client_type:
            GroqDocumentWriterAdapter(
                api_key="test-key",
                model_name="openai/gpt-oss-120b",
                max_input_tokens=128_000,
                base_url="https://api.groq.com/openai/v1/",
            )

        client_type.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.groq.com",
        )

    def test_normalizes_base_url_from_environment(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"GROQ_BASE_URL": "https://api.groq.com/openai/v1"},
            ),
            patch(
                "infrastructure.ai.groq_document_writer_adapter.AsyncGroq"
            ) as client_type,
        ):
            GroqDocumentWriterAdapter(
                api_key="test-key",
                model_name="openai/gpt-oss-120b",
                max_input_tokens=128_000,
            )

        client_type.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.groq.com",
        )


if __name__ == "__main__":
    unittest.main()
