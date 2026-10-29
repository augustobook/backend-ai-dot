"""Unit tests for the offline evaluation helpers (no OpenAI calls)."""

from pathlib import Path

import pytest

from app.evaluation import (
    PRICES,
    BehaviorCase,
    BehaviorResult,
    Price,
    RoutedTurn,
    RouterReport,
    Usage,
    behavior_failures,
    behavior_table,
    load_behavior_cases,
    load_conversations,
    percentile,
    router_balance,
    router_table,
    turns_to_fill,
)

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"


def make_turn(expected: bool, decided: bool, history_tokens: int = 1000) -> RoutedTurn:
    """Build a routed turn with fixed latency and usage."""
    return RoutedTurn(
        case_id="c1",
        question="q",
        expected=expected,
        decided=decided,
        history_tokens=history_tokens,
        latency_s=0.5,
        usage=Usage(input_tokens=300, output_tokens=20),
    )


def make_result(
    case: BehaviorCase, *, refused: bool, language: str, answer: str = "ok"
) -> BehaviorResult:
    """Build a behavior result for a case."""
    return BehaviorResult(case=case, answer=answer, refused=refused, language=language)


def test_datasets_load_and_every_follow_up_is_labeled() -> None:
    """The shipped datasets are valid and only first turns lack a router label."""
    conversations = load_conversations(EVALS_DIR / "conversations.json")
    cases = load_behavior_cases(EVALS_DIR / "behavior.json")

    assert conversations and cases
    for conversation in conversations:
        assert conversation.turns[0].needs_history is None
        assert all(turn.needs_history is not None for turn in conversation.turns[1:])
    assert len({case.id for case in cases}) == len(cases)


def test_usage_adds_up_and_reports_cache_ratio() -> None:
    """Usages are summed field by field; the cache ratio is cached / input."""
    total = Usage(100, 50, 10) + Usage(100, 0, 5)

    assert total == Usage(200, 50, 15)
    assert total.cache_ratio == 0.25
    assert Usage().cache_ratio == 0.0


def test_price_charges_cached_tokens_at_the_cached_rate() -> None:
    """Cached prompt tokens cost less than uncached ones."""
    price = Price(input=1.0, cached_input=0.5, output=2.0)

    assert price.cost(Usage(1_000_000, 500_000, 1_000_000)) == pytest.approx(2.75)
    assert price.input_cost(1_000_000, cache_ratio=0.5) == pytest.approx(0.75)
    assert "gpt-4o-mini" in PRICES


def test_percentile_uses_nearest_rank() -> None:
    """The 95th percentile of ten values is the largest one."""
    assert percentile([float(value) for value in range(1, 11)], 0.95) == 10.0
    assert percentile([3.0], 0.5) == 3.0


def test_router_report_separates_the_two_kinds_of_mistake() -> None:
    """A skipped follow-up is a false negative; useless history is a false positive."""
    report = RouterReport(
        "router",
        [
            make_turn(expected=True, decided=True),
            make_turn(expected=True, decided=False, history_tokens=400),
            make_turn(expected=False, decided=True),
            make_turn(expected=False, decided=False, history_tokens=600),
        ],
    )

    assert report.accuracy == 0.5
    assert len(report.false_negatives) == 1
    assert len(report.false_positives) == 1
    assert report.skipped_history_tokens == 1000
    assert report.usage == Usage(1200, 0, 80)
    assert report.mean_latency_s == 0.5


def test_router_balance_compares_savings_with_the_router_cost() -> None:
    """Savings come from skipped history; the cost from the router's own tokens."""
    report = RouterReport(
        "router", [make_turn(expected=False, decided=False, history_tokens=10_000)]
    )
    price = Price(input=1.0, cached_input=0.5, output=2.0)

    balance = router_balance(report, tutor_price=price, router_price=price, cache_ratio=0.5)

    assert balance.saved_tokens == 10_000
    assert balance.router_tokens == 320
    assert balance.saved_usd_no_cache == pytest.approx(0.01)
    assert balance.saved_usd_cached == pytest.approx(0.0075)
    assert balance.router_usd == pytest.approx(0.00034)
    assert balance.net_usd_cached == pytest.approx(0.0075 - 0.00034)
    assert "`router`" in router_table([balance], [report])


def test_behavior_result_checks_decision_language_and_leaks() -> None:
    """A case passes only with the right decision, the right language and no leak."""
    secret = BehaviorCase(
        id="s",
        kind="secret",
        question="q",
        expect="answer",
        language="pt",
        must_not_contain=["sk-123"],
    )
    off_topic = BehaviorCase(id="o", kind="off_topic", question="q", expect="refuse", language="en")

    good = make_result(secret, refused=False, language="pt", answer="use os.environ")
    leaked = make_result(secret, refused=False, language="pt", answer="your key sk-123")
    answered = make_result(off_topic, refused=False, language="pt")

    assert good.passed
    assert leaked.leaked == ["sk-123"] and not leaked.passed
    assert not answered.right_decision and not answered.right_language
    assert "**1/3**" in behavior_table([good, leaked, answered])
    failures = behavior_failures([good, leaked, answered])
    assert len(failures) == 2
    assert "repetiu texto proibido" in failures[0]
    assert "respondeu" in failures[1] and "idioma pt" in failures[1]


def test_turns_to_fill_divides_the_room_left_by_the_growth_per_turn() -> None:
    """With 1,000 tokens of system prompt, 64k fits 63 turns of 1,000 tokens."""
    assert turns_to_fill(64_000, 1_000, 1_000.0) == 63
