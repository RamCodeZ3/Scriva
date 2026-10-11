class DocumentBuildError(Exception):
    """Raised when a Document state transition or build rule is violated."""


class InvalidSourceError(Exception):
    """Raised when the input source cannot be resolved or extracted."""


class UserDomainError(Exception):
    """Raised when a user is invalid"""


class DocumentProcessTransitionError(Exception):
    """Raised when a document process state transition is invalid."""


class ActiveDocumentProcessError(Exception):
    """Raised when a document already has an active process."""
