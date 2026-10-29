"""Domain exceptions.

The interfaces (CLI, API, web UI) never see OpenAI-specific exceptions: the service
layer translates them into these classes, each carrying a user-friendly message and
the HTTP status code the API should answer with.
"""

from app.core.config import MAX_QUESTION_LENGTH


class ChatbotError(Exception):
    """Base class for every error raised on purpose by the chatbot.

    Attributes:
        user_message: Message that is safe and helpful to show to end users.
        status_code: HTTP status code used by the API for this error.
    """

    user_message: str = "An unexpected error occurred. Please try again."
    status_code: int = 500

    def __init__(self, user_message: str | None = None) -> None:
        """Create the error.

        Args:
            user_message: Optional override for the default user-facing message.
        """
        if user_message is not None:
            self.user_message = user_message
        super().__init__(self.user_message)


class MissingAPIKeyError(ChatbotError):
    """Raised when `OPENAI_API_KEY` is not configured."""

    user_message = (
        "The OpenAI API key is not configured. Copy `.env.example` to `.env` and set "
        "OPENAI_API_KEY=<your key> (or export it as an environment variable), "
        "then start the application again."
    )
    status_code = 503


class QuestionTooLongError(ChatbotError):
    """Raised when a question exceeds the maximum number of characters."""

    user_message = (
        f"The question is too long. Please shorten it to at most {MAX_QUESTION_LENGTH} "
        "characters and try again."
    )
    status_code = 422


class ConversationLimitError(ChatbotError):
    """Raised when a conversation no longer fits in the model's context window.

    The whole history is always sent to the model (nothing is cut), so once the
    conversation reaches the token limit the user must start a new one.
    """

    user_message = (
        "This conversation has reached its maximum size. Please start a new "
        "conversation to keep asking questions."
    )
    status_code = 409


class RateLimitExceededError(ChatbotError):
    """Raised when a client asks more questions than its rate limit allows.

    Attributes:
        retry_after: Seconds until the client may ask again.
    """

    status_code = 429

    def __init__(self, retry_after: int) -> None:
        """Create the error.

        Args:
            retry_after: Seconds until the client may ask again.
        """
        self.retry_after = retry_after
        super().__init__(
            f"Too many questions in a short time. Please wait {retry_after} seconds and try again."
        )


class LLMError(ChatbotError):
    """Base class for failures while talking to the language model."""

    user_message = "The AI service failed to answer. Please try again in a moment."
    status_code = 503


class LLMAuthenticationError(LLMError):
    """Raised when OpenAI rejects the configured API key."""

    user_message = (
        "The AI service rejected the configured API key. Check that OPENAI_API_KEY is valid."
    )
    status_code = 503


class LLMRateLimitError(LLMError):
    """Raised when the OpenAI rate limit or quota is exceeded."""

    user_message = (
        "The AI service is receiving too many requests (or the quota was exceeded). "
        "Please wait a few seconds and try again."
    )
    status_code = 429


class LLMTimeoutError(LLMError):
    """Raised when OpenAI takes too long to answer."""

    user_message = "The AI service took too long to answer. Please try again."
    status_code = 504


class LLMUnavailableError(LLMError):
    """Raised when OpenAI cannot be reached or fails unexpectedly."""

    user_message = (
        "The AI service is unavailable right now. Check your internet connection "
        "and try again in a moment."
    )
    status_code = 503
