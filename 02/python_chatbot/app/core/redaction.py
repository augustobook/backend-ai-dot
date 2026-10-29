"""Remove secrets that users paste into their questions.

Learners often paste real configuration ("my code fails: OpenAI(api_key='sk-...')").
Asking the model not to repeat the key is not enough: the evaluation caught it
pasting the key back into an `export OPENAI_API_KEY=...` example. So the secret is
replaced by a placeholder in code, before the question reaches the router, the
model, the conversation history or the LangSmith traces.

The patterns cover well-known key formats and credentials written as
`password=...` or inside URLs. Anything else still relies on the system prompt.
"""

import re

PLACEHOLDER = "[REDACTED]"

# Each pattern either matches the whole secret, or has a group named `secret`
# with just the part to replace (keeping "password=" or the URL around it).
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"),  # OpenAI / Anthropic
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),  # Google
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),  # Slack
    # scheme://user:PASSWORD@host
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:(?P<secret>[^\s@/]+)@", re.IGNORECASE),
    # password = "...", api_key: ..., token=... The value must contain a digit, so
    # code such as `token = get_token()` is not taken for a secret.
    re.compile(
        r"\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b[\"']?\s*[:=]\s*"
        r"[\"']?(?P<secret>(?=[^\s\"',;()]*\d)[^\s\"',;()]{6,})",
        re.IGNORECASE,
    ),
)


def _replace(match: re.Match[str]) -> str:
    """Replace the secret part of a match by the placeholder."""
    if "secret" not in match.re.groupindex:
        return PLACEHOLDER
    start, end = match.span("secret")
    offset = match.start()
    text = match.group(0)
    return text[: start - offset] + PLACEHOLDER + text[end - offset :]


def redact_secrets(text: str) -> tuple[str, int]:
    """Replace every secret found in a text by `PLACEHOLDER`.

    Args:
        text: The user's message.

    Returns:
        The redacted text and how many secrets were replaced.
    """
    total = 0
    for pattern in _PATTERNS:
        text, count = pattern.subn(_replace, text)
        total += count
    return text, total
