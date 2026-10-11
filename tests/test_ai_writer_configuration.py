from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api.deps import get_document_writer


class AIWriterConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_document_writer.cache_clear()

    def test_uses_configured_provider_order_and_models(self) -> None:
        environment = {
            "GEMINI_API_KEY": "gemini-test-key",
            "GEMINI_MODEL": "gemini-from-env",
            "GROQ_API_KEY": "groq-test-key",
            "GROQ_MODEL": "groq-from-env",
            "AI_PROVIDER_ORDER": "groq,gemini",
        }

        with patch.dict(os.environ, environment, clear=True):
            get_document_writer.cache_clear()
            writer = get_document_writer()

        self.assertEqual(
            [provider.provider_name for provider in writer._providers],
            ["groq", "gemini"],
        )
        self.assertEqual(
            [provider._model_name for provider in writer._providers],
            ["groq-from-env", "gemini-from-env"],
        )


if __name__ == "__main__":
    unittest.main()
