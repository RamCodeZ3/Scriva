from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from application.exceptions import AIProvidersExhaustedError
from application.ports.document_writer_port import (
    AIAttempt,
    AIWriterMetadata,
    DocumentWriterPort,
    DocumentWriterResult,
)
from domain.entities.source import Source
from domain.exceptions import DocumentBuildError, InvalidSourceError
from domain.value_objects.apa_structure import APASection
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from domain.value_objects.source_ref import SourceReference

logger = logging.getLogger(__name__)


class FallbackDocumentWriter(DocumentWriterPort):
    def __init__(
        self,
        providers: list[DocumentWriterPort],
        *,
        attempt_timeout_seconds: float = 120,
        total_budget_seconds: float = 300,
        circuit_cooldown_seconds: float = 60,
    ) -> None:
        if not providers:
            raise ValueError("At least one AI provider must be configured.")
        self._providers = providers
        self._attempt_timeout = attempt_timeout_seconds
        self._total_budget = total_budget_seconds
        self._cooldown = circuit_cooldown_seconds
        self._circuit_open_until: dict[str, float] = {}

    async def write(
        self,
        *,
        source_content: str,
        title: str,
        document_type: DocumentType,
        presentation: PresentationInfo,
        additional_notes: str | None = None,
        sources: list[Source] | None = None,
    ) -> DocumentWriterResult:
        if not source_content.strip():
            raise InvalidSourceError("Source content cannot be empty.")
        return await self._execute(
            operation="generation",
            content=source_content,
            invoke=lambda provider: provider.write(
                source_content=source_content,
                title=title,
                document_type=document_type,
                presentation=presentation,
                additional_notes=additional_notes,
                sources=sources,
            ),
        )

    async def augment(
        self,
        *,
        existing_sections: list[APASection],
        existing_references: list[SourceReference],
        new_content: str,
        document_type: DocumentType,
        existing_global_style: dict[str, Any],
        additional_notes: str | None = None,
        sources: list[Source] | None = None,
    ) -> DocumentWriterResult:
        if not new_content.strip():
            raise InvalidSourceError("New source content cannot be empty.")
        return await self._execute(
            operation="expansion",
            content=new_content,
            invoke=lambda provider: provider.augment(
                existing_sections=existing_sections,
                existing_references=existing_references,
                new_content=new_content,
                document_type=document_type,
                existing_global_style=existing_global_style,
                additional_notes=additional_notes,
                sources=sources,
            ),
        )

    async def _execute(
        self,
        *,
        operation: str,
        content: str,
        invoke: Callable[
            [DocumentWriterPort], Awaitable[DocumentWriterResult]
        ],
    ) -> DocumentWriterResult:
        started = time.monotonic()
        attempts: list[AIAttempt] = []
        for provider in self._providers:
            name = str(
                getattr(provider, "provider_name", provider.__class__.__name__)
            )
            model = str(getattr(provider, "_model_name", "unknown"))
            now = time.monotonic()
            if now - started >= self._total_budget:
                attempts.append(
                    AIAttempt(name, model, "total_budget_exhausted")
                )
                break
            if self._circuit_open_until.get(name, 0) > now:
                attempts.append(AIAttempt(name, model, "skipped_circuit_open"))
                continue
            limit = getattr(provider, "max_input_tokens", None)
            if limit is not None and _estimate_tokens(content) > int(limit):
                attempts.append(
                    AIAttempt(name, model, "skipped_context_too_large")
                )
                continue
            attempt_started = time.monotonic()
            remaining = self._total_budget - (attempt_started - started)
            try:
                result = await asyncio.wait_for(
                    invoke(provider),
                    timeout=min(self._attempt_timeout, remaining),
                )
            except (InvalidSourceError, ValueError):
                raise
            except TimeoutError as exc:
                attempts.append(
                    _failed_attempt(
                        name, model, "timeout", exc, attempt_started
                    )
                )
                continue
            except Exception as exc:
                kind = _error_kind(exc)
                attempts.append(
                    _failed_attempt(name, model, kind, exc, attempt_started)
                )
                if kind in {"rate_limit", "server_error"}:
                    self._circuit_open_until[name] = (
                        time.monotonic() + self._cooldown
                    )
                logger.warning(
                    "AI provider attempt failed provider=%s model=%s kind=%s",
                    name,
                    model,
                    kind,
                )
                continue
            latency = int((time.monotonic() - attempt_started) * 1000)
            attempts.append(
                AIAttempt(name, model, "success", latency_ms=latency)
            )
            return replace(
                result,
                metadata=AIWriterMetadata(
                    provider=name,
                    model=model,
                    attempts=tuple(attempts),
                ),
            )
        stage = (
            "ai_generation" if operation == "generation" else "ai_expansion"
        )
        raise AIProvidersExhaustedError(
            "The document could not be generated by the available AI models.",
            stage,
            tuple(attempts),
        )


def _estimate_tokens(content: str) -> int:
    return max(1, (len(content) + 3) // 4)


def _error_kind(exc: Exception) -> str:
    detail = str(exc).casefold()
    if "429" in detail or "quota" in detail or "rate limit" in detail:
        return "rate_limit"
    if any(code in detail for code in ("500", "502", "503", "504")):
        return "server_error"
    if "401" in detail or "403" in detail:
        return "authentication"
    if isinstance(exc, DocumentBuildError):
        return "invalid_response"
    return "provider_error"


def _failed_attempt(
    provider: str,
    model: str,
    kind: str,
    exc: Exception,
    started: float,
) -> AIAttempt:
    return AIAttempt(
        provider=provider,
        model=model,
        outcome="failed",
        error_kind=kind,
        error_detail=str(exc),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
