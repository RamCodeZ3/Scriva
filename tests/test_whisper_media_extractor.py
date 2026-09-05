import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.entities.source import SourceType, classify_source
from domain.exceptions import InvalidSourceError
from infrastructure.extractors.file_extractor_adapter import (
    FileExtractorAdapter,
)
from infrastructure.extractors.whisper_media_extractor_adapter import (
    WhisperMediaExtractorAdapter,
)


class WhisperMediaExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribes_ffmpeg_supported_file(self) -> None:
        model = Mock()
        model.device = SimpleNamespace(type="cpu")
        model.transcribe.return_value = {"text": "  Transcript text  "}
        loader = Mock(return_value=model)
        extractor = WhisperMediaExtractorAdapter(model_loader=loader)

        with tempfile.NamedTemporaryFile(suffix=".aac") as media_file:
            with patch(
                "infrastructure.extractors.whisper_media_extractor_adapter."
                "shutil.which",
                return_value="/usr/bin/ffmpeg",
            ):
                result = await extractor.extract(media_file.name)

        self.assertEqual(result, "Transcript text")
        loader.assert_called_once_with("base", device=None)
        model.transcribe.assert_called_once_with(
            media_file.name,
            fp16=False,
        )

    async def test_reuses_loaded_model(self) -> None:
        model = Mock()
        model.device = SimpleNamespace(type="cuda")
        model.transcribe.return_value = {"text": "Transcript"}
        loader = Mock(return_value=model)
        extractor = WhisperMediaExtractorAdapter(model_loader=loader)

        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            with patch(
                "infrastructure.extractors.whisper_media_extractor_adapter."
                "shutil.which",
                return_value="/usr/bin/ffmpeg",
            ):
                await extractor.extract(media_file.name)
                await extractor.extract(media_file.name)

        loader.assert_called_once()
        model.transcribe.assert_called_with(media_file.name, fp16=True)

    async def test_rejects_empty_transcript(self) -> None:
        model = Mock()
        model.device = SimpleNamespace(type="cpu")
        model.transcribe.return_value = {"text": "  "}
        extractor = WhisperMediaExtractorAdapter(
            model_loader=Mock(return_value=model)
        )

        with tempfile.NamedTemporaryFile(suffix=".ogg") as media_file:
            with patch(
                "infrastructure.extractors.whisper_media_extractor_adapter."
                "shutil.which",
                return_value="/usr/bin/ffmpeg",
            ):
                with self.assertRaisesRegex(
                    InvalidSourceError, "empty transcript"
                ):
                    await extractor.extract(media_file.name)

    async def test_file_extractor_delegates_unknown_media_format(self) -> None:
        media_extractor = Mock()
        media_extractor.extract = Mock(return_value=None)

        async def extract(raw: str) -> str:
            return f"transcribed:{raw}"

        media_extractor.extract.side_effect = extract
        extractor = FileExtractorAdapter(media_extractor=media_extractor)

        with tempfile.NamedTemporaryFile(suffix=".mka") as media_file:
            result = await extractor.extract(media_file.name)

        self.assertEqual(result, f"transcribed:{media_file.name}")

    def test_classifies_existing_unknown_format_as_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording.mka"
            path.touch()
            source_type, file_kind = classify_source(str(path))

        self.assertEqual(source_type, SourceType.FILE)
        self.assertIsNone(file_kind)


if __name__ == "__main__":
    unittest.main()
