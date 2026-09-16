from __future__ import annotations

from abc import ABC, abstractmethod


class GoogleOAuthTokenPort(ABC):
    @abstractmethod
    async def exchange_authorization_code(
        self,
        authorization_code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> str:
        """Exchange an OAuth code and return its refresh token."""
        raise NotImplementedError

    @abstractmethod
    async def get_access_token(self, refresh_token: str) -> str:
        """Return a current access token for a stored refresh token."""
        raise NotImplementedError
