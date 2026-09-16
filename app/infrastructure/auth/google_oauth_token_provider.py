from __future__ import annotations

import asyncio

from application.exceptions import GoogleAuthorizationError
from application.ports.google_oauth_token_port import GoogleOAuthTokenPort
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from requests import RequestException, post

GOOGLE_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class GoogleOAuthTokenProvider(GoogleOAuthTokenPort):
    _TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    async def exchange_authorization_code(
        self,
        authorization_code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._exchange_sync,
            authorization_code,
            redirect_uri,
            code_verifier,
        )

    async def get_access_token(self, refresh_token: str) -> str:
        return await asyncio.to_thread(self._refresh_sync, refresh_token)

    def _refresh_sync(self, refresh_token: str) -> str:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_uri=self._TOKEN_URL,
        )
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise ValueError(
                f"Could not refresh Google access token: {exc}"
            ) from exc

        return credentials.token

    def _exchange_sync(
        self,
        authorization_code: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> str:
        payload = {
            "code": authorization_code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier
        try:
            response = post(self._TOKEN_URL, data=payload, timeout=15)
            response.raise_for_status()
            token_data = response.json()
        except (RequestException, ValueError) as exc:
            raise GoogleAuthorizationError(
                "Could not exchange the Google authorization code."
            ) from exc

        refresh_token = (
            token_data.get("refresh_token")
            if isinstance(token_data, dict)
            else None
        )
        if not isinstance(refresh_token, str) or not refresh_token:
            raise GoogleAuthorizationError(
                "Google did not return a refresh token. Request offline "
                "access with consent and try again."
            )
        return refresh_token
