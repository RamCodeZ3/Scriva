from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from infrastructure.export.document_exporter_resolver_adapter import (
    DocumentExporterResolverAdapter,
)


class GoogleDocsExporterResolverTest(unittest.TestCase):
    def test_resolves_fresh_credentials_for_every_google_docs_export(
        self,
    ) -> None:
        user_id = uuid4()
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.side_effect = [
            "refresh-token-1",
            "refresh-token-2",
        ]
        token_provider = AsyncMock()
        token_provider.get_access_token.side_effect = [
            "access-token-1",
            "access-token-2",
        ]
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
        )

        first = asyncio.run(resolver.resolve("google_docs", user_id))
        second = asyncio.run(resolver.resolve("google_docs", user_id))

        self.assertIsNot(first, second)
        self.assertEqual(first._credentials.token, "access-token-1")
        self.assertEqual(second._credentials.token, "access-token-2")
        self.assertEqual(
            credentials_repository.get_refresh_token.await_args_list,
            [unittest.mock.call(user_id), unittest.mock.call(user_id)],
        )
        self.assertEqual(
            token_provider.get_access_token.await_args_list,
            [
                unittest.mock.call("refresh-token-1"),
                unittest.mock.call("refresh-token-2"),
            ],
        )

    def test_keeps_legacy_google_doc_export_target(self) -> None:
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.return_value = "refresh"
        token_provider = AsyncMock()
        token_provider.get_access_token.return_value = "access"
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
        )

        exporter = asyncio.run(resolver.resolve("google_doc", uuid4()))

        self.assertEqual(exporter._credentials.token, "access")
