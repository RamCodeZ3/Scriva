from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api.deps import get_document_writer


class AIWriterConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_document_writer.cache_clear()

    def test_default_model_priority(self) -> None:
        self.assertEqual(
            self._models({"GEMINI_API_KEY": "test-key"}),
            [
                "gemini-3.8-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ],
        )

    def test_configured_order_removes_blanks_and_duplicates(self) -> None:
        self.assertEqual(
            self._models(
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODELS": " second, ,first,second ",
                }
            ),
            ["second", "first"],
        )

    def test_legacy_model_does_not_override_configured_order(self) -> None:
        self.assertEqual(
            self._models(
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODEL": "primary",
                    "GEMINI_MODELS": "secondary,primary",
                }
            ),
            ["secondary", "primary"],
        )

    def test_missing_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            self._models({})

    def test_empty_model_list_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "GEMINI_MODELS"):
            self._models(
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODELS": " , ",
                }
            )

    def _models(self, environment: dict[str, str]) -> list[str]:
        with patch.dict(os.environ, environment, clear=True):
            get_document_writer.cache_clear()
            writer = get_document_writer()
        self.assertTrue(
            all(
                provider.provider_name == "gemini"
                for provider in writer._providers
            )
        )
        return [provider._model_name for provider in writer._providers]


if __name__ == "__main__":
    unittest.main()
