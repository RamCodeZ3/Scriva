class ApplicationError(Exception):
    """Base class for every error raised by the application layer."""


class DocumentNotFoundError(ApplicationError):
    pass


class SourceNotFoundError(ApplicationError):
    pass


class SourceAccessDeniedError(ApplicationError):
    """Raised when a user requests sources owned by another account."""


class UserNotFoundError(ApplicationError):
    pass


class UserAlreadyExistsError(ApplicationError):
    pass


class UnsupportedSourceTypeError(ApplicationError):
    pass


class DocumentAccessDeniedError(ApplicationError):
    """Raised when a document is accessed by a user who does not own it."""


class NoSourcesExtractedError(ApplicationError):
    """Raised when *every* source of a document/augment operation failed
    extraction, so there is no content left to hand to the writer."""


class GoogleAuthorizationError(ApplicationError):
    """Raised when Google cannot issue credentials for the user."""


class AIProvidersExhaustedError(ApplicationError):
    """Raised when every configured AI provider failed an operation."""

    def __init__(self, message: str, stage: str, attempts: tuple) -> None:
        super().__init__(message)
        self.stage = stage
        self.attempts = attempts
