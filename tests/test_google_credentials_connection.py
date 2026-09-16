from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from application.exceptions import GoogleAuthorizationError
from application.use_cases.connect_google_credentials_use_case import (
    ConnectGoogleCredentialsInput,
    ConnectGoogleCredentialsUseCase,
)
from cryptography.fernet import Fernet
from infrastructure.auth.google_oauth_token_provider import (
    GoogleOAuthTokenProvider,
)
from infrastructure.persistence.supabase_google_credentials_repository import (
    SupabaseGoogleCredentialsRepository,
)


class ConnectGoogleCredentialsUseCaseTest(unittest.TestCase):
    def test_exchanges_and_saves_refresh_token_for_authenticated_user(
        self,
    ) -> None:
        user_id = uuid4()
        credentials = AsyncMock()
        oauth_tokens = AsyncMock()
        oauth_tokens.exchange_authorization_code.return_value = "refresh-token"
        use_case = ConnectGoogleCredentialsUseCase(credentials, oauth_tokens)

        asyncio.run(
            use_case.execute(
                ConnectGoogleCredentialsInput(
                    user_id=user_id,
                    authorization_code="authorization-code",
                    redirect_uri="https://app.example.com/google/callback",
                    code_verifier="v" * 43,
                )
            )
        )

        oauth_tokens.exchange_authorization_code.assert_awaited_once_with(
            "authorization-code",
            "https://app.example.com/google/callback",
            "v" * 43,
        )
        credentials.save_refresh_token.assert_awaited_once_with(
            user_id, "refresh-token"
        )


class GoogleOAuthTokenProviderTest(unittest.TestCase):
    @patch("infrastructure.auth.google_oauth_token_provider.post")
    def test_exchanges_code_with_offline_refresh_token(
        self, post: Mock
    ) -> None:
        response = Mock()
        response.json.return_value = {"refresh_token": "refresh-token"}
        post.return_value = response
        provider = GoogleOAuthTokenProvider("client-id", "client-secret")

        refresh_token = provider._exchange_sync(
            "authorization-code",
            "https://app.example.com/google/callback",
            "v" * 43,
        )

        self.assertEqual(refresh_token, "refresh-token")
        response.raise_for_status.assert_called_once_with()
        post.assert_called_once_with(
            "https://oauth2.googleapis.com/token",
            data={
                "code": "authorization-code",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "redirect_uri": "https://app.example.com/google/callback",
                "grant_type": "authorization_code",
                "code_verifier": "v" * 43,
            },
            timeout=15,
        )

    @patch("infrastructure.auth.google_oauth_token_provider.post")
    def test_rejects_response_without_refresh_token(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"access_token": "temporary-token"}
        post.return_value = response
        provider = GoogleOAuthTokenProvider("client-id", "client-secret")

        with self.assertRaisesRegex(
            GoogleAuthorizationError, "did not return a refresh token"
        ):
            provider._exchange_sync(
                "authorization-code",
                "https://app.example.com/google/callback",
                None,
            )


class SupabaseGoogleCredentialsRepositoryTest(unittest.TestCase):
    def test_encrypts_refresh_token_before_upsert(self) -> None:
        key = Fernet.generate_key()
        client = Mock()
        table = client.table.return_value
        table.upsert.return_value = table
        repository = SupabaseGoogleCredentialsRepository(client, key.decode())
        user_id = uuid4()

        run_sync = AsyncMock(
            side_effect=lambda function, *args: function(*args)
        )
        with patch(
            "infrastructure.persistence."
            "supabase_google_credentials_repository.asyncio.to_thread",
            run_sync,
        ):
            asyncio.run(
                repository.save_refresh_token(user_id, "refresh-token")
            )

        client.table.assert_called_once_with("google_credentials")
        payload = table.upsert.call_args.args[0]
        self.assertEqual(payload["user_id"], str(user_id))
        self.assertNotEqual(
            payload["encrypted_refresh_token"], "refresh-token"
        )
        self.assertEqual(
            Fernet(key)
            .decrypt(payload["encrypted_refresh_token"].encode())
            .decode(),
            "refresh-token",
        )
        self.assertEqual(
            table.upsert.call_args.kwargs, {"on_conflict": "user_id"}
        )
        table.execute.assert_called_once_with()
