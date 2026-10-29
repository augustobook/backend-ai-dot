"""Domain exceptions raised by the service layer.

These exceptions know nothing about HTTP. They are translated into HTTP
responses by the exception handlers registered in `app.main`.
"""


class DomainError(Exception):
    """Base class for all domain errors raised by the application."""


class BookNotFoundError(DomainError):
    """Raised when a book with the requested id does not exist.

    Attributes:
        book_id: The id that was looked up.
    """

    def __init__(self, book_id: int) -> None:
        """Initialize the error with the missing book id.

        Args:
            book_id: The id that was looked up.
        """
        self.book_id = book_id
        super().__init__(f"Book with id {book_id} not found")
