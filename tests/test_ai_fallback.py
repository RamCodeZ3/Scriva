from __future__ import annotations

import asyncio
import unittest
from typing import Any

from application.exceptions import AIProvidersExhaustedError
from application.ports.document_writer_port import (
    AIWriterMetadata,
    DocumentWriterResult,
)
from domain.exceptions import InvalidSourceError
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from infrastructure.ai.fallback_document_writer import FallbackDocumentWriter


class _Provider:
    def __init__(
        self,
        name: str,
        *,
        error: Exception | None = None,
        delay: float = 0,
        max_input_tokens: int = 1000,
    ) -> None:
        self.provider_name = name
        self._model_name = f"{name}-model"
        self.max_input_tokens = max_input_tokens
        self.error = error
        self.delay = delay
        self.calls: list[str] = []

    async def write(self, **kwargs: Any) -> DocumentWriterResult:
        return await self._result("generation")

    async def augment(self, **kwargs: Any) -> DocumentWriterResult:
        return await self._result("expansion")

    async def _result(self, operation: str) -> DocumentWriterResult:
        self.calls.append(operation)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return DocumentWriterResult(
            title="Generated",
            sections=[],
            references=[],
            global_style={},
            metadata=AIWriterMetadata(self.provider_name, self._model_name),
        )


class FallbackDocumentWriterTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_providers_in_order_and_returns_success_metadata(
        self,
    ) -> None:
        first = _Provider("gemini", error=RuntimeError("broken JSON"))
        second = _Provider("groq")
        writer = FallbackDocumentWriter([first, second])

        result = await self._write(writer)

        self.assertEqual(first.calls, ["generation"])
        self.assertEqual(second.calls, ["generation"])
        self.assertEqual(result.metadata.provider, "groq")
        self.assertEqual(
            [attempt.outcome for attempt in result.metadata.attempts],
            ["failed", "success"],
        )

    async def test_context_too_large_skips_provider(self) -> None:
        first = _Provider("small", max_input_tokens=1)
        second = _Provider("groq")
        writer = FallbackDocumentWriter([first, second])

        result = await self._write(writer, content="content long enough")

        self.assertEqual(first.calls, [])
        self.assertEqual(
            result.metadata.attempts[0].outcome,
            "skipped_context_too_large",
        )

    async def test_timeout_moves_to_next_provider(self) -> None:
        slow = _Provider("slow", delay=0.05)
        fallback = _Provider("groq")
        writer = FallbackDocumentWriter(
            [slow, fallback], attempt_timeout_seconds=0.01
        )

        result = await self._write(writer)

        self.assertEqual(result.metadata.provider, "groq")
        self.assertEqual(result.metadata.attempts[0].error_kind, "timeout")

    async def test_rate_limit_opens_circuit_breaker(self) -> None:
        limited = _Provider("gemini", error=RuntimeError("HTTP 429"))
        fallback = _Provider("groq")
        writer = FallbackDocumentWriter(
            [limited, fallback], circuit_cooldown_seconds=60
        )

        await self._write(writer)
        result = await self._write(writer)

        self.assertEqual(limited.calls, ["generation"])
        self.assertEqual(
            result.metadata.attempts[0].outcome,
            "skipped_circuit_open",
        )

    async def test_empty_input_does_not_call_any_provider(self) -> None:
        provider = _Provider("gemini")
        writer = FallbackDocumentWriter([provider])

        with self.assertRaises(InvalidSourceError):
            await self._write(writer, content=" ")

        self.assertEqual(provider.calls, [])

    async def test_all_failures_include_stage_and_attempts(self) -> None:
        provider = _Provider("gemini", error=RuntimeError("HTTP 503"))
        writer = FallbackDocumentWriter([provider])

        with self.assertRaises(AIProvidersExhaustedError) as captured:
            await self._write(writer)

        self.assertEqual(captured.exception.stage, "ai_generation")
        self.assertEqual(len(captured.exception.attempts), 1)

    async def test_augmentation_uses_expansion_stage(self) -> None:
        provider = _Provider("gemini", error=RuntimeError("invalid schema"))
        writer = FallbackDocumentWriter([provider])

        with self.assertRaises(AIProvidersExhaustedError) as captured:
            await writer.augment(
                existing_sections=[],
                existing_references=[],
                new_content="new content",
                document_type=DocumentType.SUMMARY,
                existing_global_style={},
            )

        self.assertEqual(captured.exception.stage, "ai_expansion")
        self.assertEqual(provider.calls, ["expansion"])

    @staticmethod
    async def _write(
        writer: FallbackDocumentWriter,
        content: str = "source content",
    ) -> DocumentWriterResult:
        return await writer.write(
            source_content=content,
            title="Title",
            document_type=DocumentType.SUMMARY,
            presentation=PresentationInfo(student_name="Student"),
        )


if __name__ == "__main__":
    unittest.main()
