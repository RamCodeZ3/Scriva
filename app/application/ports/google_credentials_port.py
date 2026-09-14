from abc import ABC, abstractmethod
from uuid import UUID


class GoogleCredentialsPort(ABC):
    @abstractmethod
    async def save_refresh_token(
        self, user_id: UUID, refresh_token: str
    ) -> None:
        """Encrypt and persist the user's latest Google refresh token."""
        raise NotImplementedError

    @abstractmethod
    async def get_refresh_token(self, user_id: UUID) -> str | None:
        """
        Returns the decrypted refresh_token, or None if the user
        hasn't granted Google Docs/Drive access yet.
        """
        raise NotImplementedError
