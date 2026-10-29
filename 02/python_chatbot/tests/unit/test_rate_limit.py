"""Tests of the per-client rate limiter and of the client IP resolution."""

import pytest

from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import DAY, MINUTE, RateLimit, RateLimiter, resolve_client_ip


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current time."""
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    """A clock the test moves forward."""
    return FakeClock()


def test_limit_per_minute_refuses_and_resets(clock: FakeClock) -> None:
    """Above the limit a question is refused until the window ends."""
    limiter = RateLimiter([RateLimit(2, MINUTE)], clock=clock)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")

    clock.now = 20
    with pytest.raises(RateLimitExceededError) as error:
        limiter.check("1.2.3.4")
    assert error.value.retry_after == 40
    assert error.value.status_code == 429

    clock.now = MINUTE
    limiter.check("1.2.3.4")


def test_clients_are_counted_separately(clock: FakeClock) -> None:
    """One client using up its limit does not affect another."""
    limiter = RateLimiter([RateLimit(1, MINUTE)], clock=clock)
    limiter.check("1.2.3.4")

    limiter.check("5.6.7.8")
    with pytest.raises(RateLimitExceededError):
        limiter.check("1.2.3.4")


def test_daily_limit_applies_across_minutes(clock: FakeClock) -> None:
    """The daily limit holds even when the per-minute windows reset."""
    limiter = RateLimiter([RateLimit(10, MINUTE), RateLimit(3, DAY)], clock=clock)
    for minute in range(3):
        clock.now = minute * MINUTE
        limiter.check("1.2.3.4")

    clock.now = 3 * MINUTE
    with pytest.raises(RateLimitExceededError) as error:
        limiter.check("1.2.3.4")
    assert error.value.retry_after == DAY - 3 * MINUTE


def test_refused_questions_are_not_counted(clock: FakeClock) -> None:
    """Retrying while blocked does not use up the daily limit."""
    limiter = RateLimiter([RateLimit(1, MINUTE), RateLimit(2, DAY)], clock=clock)
    limiter.check("1.2.3.4")
    for _ in range(5):
        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    clock.now = MINUTE
    limiter.check("1.2.3.4")  # second question of the day, still allowed


def test_zero_disables_a_limit(clock: FakeClock) -> None:
    """A limit of 0 is ignored."""
    limiter = RateLimiter([RateLimit(0, MINUTE), RateLimit(0, DAY)], clock=clock)
    for _ in range(1000):
        limiter.check("1.2.3.4")


def test_expired_windows_are_purged(clock: FakeClock) -> None:
    """Old clients are forgotten once many are tracked."""
    limiter = RateLimiter([RateLimit(1, MINUTE)], clock=clock)
    limiter._PURGE_THRESHOLD = 2
    for ip in ("a", "b", "c"):
        limiter.check(ip)

    clock.now = MINUTE
    limiter.check("d")

    assert set(limiter._windows) == {("d", 0)}


# --- Client IP -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "expected"),
    [
        pytest.param("8.8.8.8", None, "8.8.8.8", id="direct-client"),
        # A public peer is the client itself: its header could be forged.
        pytest.param("8.8.8.8", "1.1.1.1", "8.8.8.8", id="public-peer-ignores-header"),
        # front Caddy -> project Caddy -> app: client, front Caddy (private).
        pytest.param("172.18.0.3", "9.9.9.9, 172.18.0.2", "9.9.9.9", id="two-proxies"),
        # A value forged by the client sits on the left and is never reached.
        pytest.param("172.18.0.3", "6.6.6.6, 9.9.9.9, 172.18.0.2", "9.9.9.9", id="forged-left"),
        pytest.param("127.0.0.1", "garbage, 172.18.0.2", "172.18.0.2", id="garbage-stops"),
        pytest.param("172.18.0.3", "10.0.0.5", "10.0.0.5", id="only-private"),
        pytest.param("172.18.0.3", None, "172.18.0.3", id="private-without-header"),
        pytest.param(None, None, "unknown", id="no-peer"),
        pytest.param("testclient", "1.1.1.1", "testclient", id="non-ip-peer"),
    ],
)
def test_resolve_client_ip(peer: str | None, forwarded_for: str | None, expected: str) -> None:
    """The client is the rightmost public address added by the trusted proxies."""
    assert resolve_client_ip(peer, forwarded_for) == expected
