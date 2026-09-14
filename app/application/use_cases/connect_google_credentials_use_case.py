from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from application.ports.google_credentials_port import GoogleCredentialsPort
from application.ports.google_oauth_token_port import GoogleOAuthTokenPort


@dataclass(frozen=True)
class ConnectGoogleCredentialsInput:
    user_id: UUID
    authorization_code: str
    redirect_uri: str
    code_verifier: str | None = None


class ConnectGoogleCredentialsUseCase:
    def __init__(
        self,
        credentials: GoogleCredentialsPort,
        oauth_tokens: GoogleOAuthTokenPort,
    ) -> None:
        self._credentials = credentials
        self._oauth_tokens = oauth_tokens

    async def execute(self, data: ConnectGoogleCredentialsInput) -> None:
        refresh_token = await self._oauth_tokens.exchange_authorization_code(
            data.authorization_code,
            data.redirect_uri,
            data.code_verifier,
        )
        await self._credentials.save_refresh_token(data.user_id, refresh_token)
