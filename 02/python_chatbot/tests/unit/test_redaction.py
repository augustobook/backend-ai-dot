"""Unit tests for the removal of pasted secrets."""

import pytest

from app.core.redaction import PLACEHOLDER, redact_secrets


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ('client = OpenAI(api_key="sk-proj-Xq7TESTe9KeyAbc123")', "sk-proj-Xq7TESTe9KeyAbc123"),
        ("token ghp_" + "a" * 36, "ghp_" + "a" * 36),
        ("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("postgresql://admin:S3cretPass99@db.internal:5432/app", "S3cretPass99"),
        ('password = "hunter2hunter2"', "hunter2hunter2"),
        ("API_KEY: abcdef123456", "abcdef123456"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
            "MIIEow",
        ),
    ],
)
def test_known_secret_formats_are_replaced(text: str, secret: str) -> None:
    """The secret disappears and the placeholder takes its place."""
    redacted, count = redact_secrets(text)

    assert secret not in redacted
    assert PLACEHOLDER in redacted
    assert count >= 1


def test_context_around_the_secret_is_kept() -> None:
    """Only the secret is replaced, so the question still makes sense."""
    redacted, _ = redact_secrets("connect to postgresql://admin:S3cretPass99@db:5432/app")

    assert redacted == f"connect to postgresql://admin:{PLACEHOLDER}@db:5432/app"


@pytest.mark.parametrize(
    "text",
    [
        "How do I read a password from input without echoing it?",
        "O que faz o módulo secrets?",
        "Use https://docs.python.org/3/library/os.html",
        "token = get_token()",
    ],
)
def test_ordinary_questions_are_untouched(text: str) -> None:
    """Questions that only talk about secrets are not changed."""
    assert redact_secrets(text) == (text, 0)
