from __future__ import annotations

import asyncio
import os
import shutil
import threading
from collections.abc import Callable
from typing import Any

from application.ports.source_extractor_port import SourceExtractorPort
from domain.exceptions import InvalidSourceError


class WhisperMediaExtractorAdapter(SourceExtractorPort):
    """Transcribe local audio or video files with OpenAI Whisper."""

    def __init__(
        self,
        model_name: str = "base",
        device: str | None = None,
        model_loader: Callable[..., Any] | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._model_loader = model_loader
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._transcription_lock = threading.Lock()

    async def extract(self, raw: str) -> str:
        if not os.path.isfile(raw):
            raise InvalidSourceError(f"Media file not found: '{raw}'.")
        if shutil.which("ffmpeg") is None:
            raise InvalidSourceError(
                "FFmpeg is required to transcribe audio and video files."
            )

        try:
            text = await asyncio.to_thread(self._transcribe_sync, raw)
        except InvalidSourceError:
            raise
        except Exception as exc:
            raise InvalidSourceError(
                f"Could not transcribe media file '{raw}': {exc}"
            ) from exc

        text = text.strip()
        if not text:
            raise InvalidSourceError(
                f"Media file '{raw}' produced an empty transcript."
            )
        return text

    def _transcribe_sync(self, path: str) -> str:
        model = self._get_model()
        device_type = getattr(getattr(model, "device", None), "type", "cpu")
        with self._transcription_lock:
            result = model.transcribe(path, fp16=device_type == "cuda")
        text = result.get("text")
        if not isinstance(text, str):
            raise InvalidSourceError(
                "Whisper returned a transcript with an invalid structure."
            )
        return text

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                loader = self._model_loader or self._default_model_loader
                self._model = loader(self._model_name, device=self._device)
        return self._model

    @staticmethod
    def _default_model_loader(model_name: str, device: str | None) -> Any:
        import whisper

        return whisper.load_model(model_name, device=device)
