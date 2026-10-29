"""Per-client limit of questions (per minute and per day).

Every question costs OpenAI tokens, so the public interfaces (web UI and API) bound
how many questions one client (IP address) may ask. The CLI runs locally and is
never limited.

State lives in memory: each process counts separately and counters reset on
restart. That fits the single-container deployment; several replicas would need a
shared store (e.g. Redis).
"""

import ipaddress
import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError

MINUTE = 60
DAY = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RateLimit:
    """At most `max_requests` questions every `window_seconds`.

    Attributes:
        max_requests: Questions allowed per window (0 disables the limit).
        window_seconds: Window length in seconds.
    """

    max_requests: int
    window_seconds: int


class RateLimiter:
    """Fixed-window question counter per client, with one or more limits.

    A question is accepted only when it fits in every limit (e.g. 10 per minute
    *and* 100 per day); a refused question is not counted.
    """

    # Above this many tracked windows, expired ones are purged.
    _PURGE_THRESHOLD = 10_000

    def __init__(
        self, limits: Sequence[RateLimit], clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Create the limiter.

        Args:
            limits: Limits to enforce; those with `max_requests == 0` are ignored.
            clock: Monotonic clock, injectable for tests.
        """
        self._limits = tuple(limit for limit in limits if limit.max_requests > 0)
        self._clock = clock
        # (client, index of the limit) -> (window start, questions in the window)
        self._windows: dict[tuple[str, int], tuple[float, int]] = {}
        # FastAPI runs sync dependencies in a thread pool, so access is guarded.
        self._lock = threading.Lock()

    def check(self, client: str) -> None:
        """Register one question of a client, or refuse it.

        Args:
            client: Client identifier (its IP address).

        Raises:
            RateLimitExceededError: If any limit is already used up; `retry_after`
                is the longest wait among the exhausted limits.
        """
        with self._lock:
            now = self._clock()
            if len(self._windows) > self._PURGE_THRESHOLD:
                self._purge(now)

            windows: list[tuple[float, int]] = []
            retry_after = 0.0
            for index, limit in enumerate(self._limits):
                start, count = self._windows.get((client, index), (now, 0))
                if now - start >= limit.window_seconds:
                    start, count = now, 0
                if count >= limit.max_requests:
                    retry_after = max(retry_after, start + limit.window_seconds - now)
                windows.append((start, count))

            if retry_after > 0:
                raise RateLimitExceededError(retry_after=max(math.ceil(retry_after), 1))

            for index, (start, count) in enumerate(windows):
                self._windows[(client, index)] = (start, count + 1)

    def _purge(self, now: float) -> None:
        """Forget windows that have already expired.

        Args:
            now: Current clock value.
        """
        self._windows = {
            key: (start, count)
            for key, (start, count) in self._windows.items()
            if now - start < self._limits[key[1]].window_seconds
        }


def _is_private(address: str) -> bool:
    """Tell whether an address is private (loopback, LAN, Docker network)."""
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False


def resolve_client_ip(peer: str | None, forwarded_for: str | None) -> str:
    """Return the IP address of the client behind the reverse proxies.

    In production the request goes client -> front Caddy -> project Caddy -> app,
    so the peer is a private (Docker) address and each proxy appends the address it
    received the request from to `X-Forwarded-For`. The header is read from the
    right, skipping private addresses (the proxies): the first public one is the
    client. Values the client forged sit further left and are never reached.

    A public peer means there is no proxy in front of the app, so the header is
    ignored: the client itself could have written it.

    Args:
        peer: Address of the direct connection (None when unknown).
        forwarded_for: Value of the `X-Forwarded-For` header, if any.

    Returns:
        The client IP (or the peer when no better address is known).
    """
    client = peer or "unknown"
    if not forwarded_for or not _is_private(client):
        return client

    for candidate in reversed(forwarded_for.split(",")):
        candidate = candidate.strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            # Garbage in the header: stop trusting anything further left.
            break
        client = candidate
        if not _is_private(candidate):
            break
    return client


@lru_cache
def get_default_rate_limiter() -> RateLimiter:
    """Return the process-wide limiter built from the settings.

    Returns:
        The shared `RateLimiter` (10 per minute and 100 per day by default).
    """
    settings = get_settings()
    return RateLimiter(
        [
            RateLimit(settings.rate_limit_per_minute, MINUTE),
            RateLimit(settings.rate_limit_per_day, DAY),
        ]
    )
