"""Retrieval evaluation: how often the expected article comes back, and how high.

The evaluation sets (`data/eval/*.json`) hold questions written the way users write
them, each with the article(s) that answer it. A search is evaluated at the article
level, the level of the results:

- hit@1: the first result is an expected article;
- hit@5: an expected article is among the first five results (recall@5 when one
  relevant article per query is enough, which is how the set is written);
- MRR@10: mean of 1 / (position of the first expected article), 0 when it is not in
  the first ten. It rewards ranking the answer higher, not only finding it.

A question with no expected article (`relevant: []`) is out of scope: nothing in the
collection answers it. Those questions do not enter the metrics above; they measure
the relevance threshold of re-ranked searches instead:

- answers shown: among the in-scope questions whose first result is right, the share
  the cross-encoder flags as relevant (a right answer flagged "low relevance" is
  hidden behind a warning in the interfaces);
- out of scope blocked: the share of out-of-scope questions whose first result is
  flagged as not relevant (or that return nothing).

Comparing these numbers across configurations (BM25, dense, hybrid, re-ranking,
rewrite...) is what tells whether a technique helps, instead of judging it from a
couple of hand-picked queries.
"""

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.services.results import SearchResponse

EVAL_TOP_K = 10


class EvalQuery(BaseModel):
    """One question of the evaluation set.

    Attributes:
        id: Identifier (`q01`...).
        kind: "lay" (popular words), "english", "exact" (a literal term) or, for
            out-of-scope questions, "ood-far" / "ood-near" (unrelated to health /
            health topics the collection does not cover).
        query: The question, as a user would type it.
        relevant: Ids of the articles that answer it (any one counts as a hit);
            empty when the question is out of scope.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    query: str
    relevant: list[str]

    @property
    def in_scope(self) -> bool:
        """Whether some article of the collection answers the question."""
        return bool(self.relevant)


@dataclass(frozen=True)
class QueryOutcome:
    """Where the first expected article landed for one query.

    Attributes:
        query: The evaluated question.
        rank: 1-based position of the first expected article, None when absent.
        returned: Article ids returned, best first.
        latency_ms: Total search time.
        top_relevant: Relevance flag of the first result (None when the search was
            not re-ranked; False when nothing was returned).
    """

    query: EvalQuery
    rank: int | None
    returned: list[str]
    latency_ms: float
    top_relevant: bool | None = None


@dataclass
class EvalReport:
    """Aggregated metrics of one configuration over the evaluation set.

    Attributes:
        name: Name of the configuration.
        outcomes: One outcome per query.
    """

    name: str
    outcomes: list[QueryOutcome] = field(default_factory=list)

    @property
    def in_scope(self) -> list[QueryOutcome]:
        """Outcomes of the questions some article answers."""
        return [o for o in self.outcomes if o.query.in_scope]

    @property
    def out_of_scope(self) -> list[QueryOutcome]:
        """Outcomes of the questions nothing in the collection answers."""
        return [o for o in self.outcomes if not o.query.in_scope]

    def hit_at(self, k: int) -> float:
        """Share of in-scope queries whose expected article is in the first `k` results.

        Args:
            k: Cut-off.

        Returns:
            A value in [0, 1].
        """
        outcomes = self.in_scope
        if not outcomes:
            return 0.0
        hits = sum(1 for outcome in outcomes if outcome.rank is not None and outcome.rank <= k)
        return hits / len(outcomes)

    @property
    def mrr(self) -> float:
        """Mean reciprocal rank of the in-scope queries over the first `EVAL_TOP_K` results.

        Returns:
            A value in [0, 1].
        """
        outcomes = self.in_scope
        if not outcomes:
            return 0.0
        return statistics.fmean(
            1.0 / outcome.rank if outcome.rank is not None else 0.0 for outcome in outcomes
        )

    @property
    def answers_shown(self) -> float | None:
        """Share of right first results that the cross-encoder flags as relevant.

        Returns:
            A value in [0, 1], or None when the search was not re-ranked or no first
            result was right.
        """
        right = [o for o in self.in_scope if o.rank == 1 and o.top_relevant is not None]
        if not right:
            return None
        return sum(1 for o in right if o.top_relevant) / len(right)

    @property
    def out_of_scope_blocked(self) -> float | None:
        """Share of out-of-scope queries whose first result is flagged as not relevant.

        Returns:
            A value in [0, 1], or None without re-ranking or out-of-scope queries.
        """
        flagged = [o for o in self.out_of_scope if o.top_relevant is not None]
        if not flagged:
            return None
        return sum(1 for o in flagged if not o.top_relevant) / len(flagged)

    @property
    def mean_latency_ms(self) -> float:
        """Average search time.

        Returns:
            Milliseconds.
        """
        return statistics.fmean(o.latency_ms for o in self.outcomes) if self.outcomes else 0.0

    def misses(self, k: int = 5) -> list[QueryOutcome]:
        """Return the in-scope queries whose expected article is not in the first `k`.

        Args:
            k: Cut-off.

        Returns:
            The failed outcomes.
        """
        return [o for o in self.in_scope if o.rank is None or o.rank > k]

    def leaks(self) -> list[QueryOutcome]:
        """Return the out-of-scope queries whose first result was flagged as relevant.

        Returns:
            The outcomes that would be shown as a confident answer.
        """
        return [o for o in self.out_of_scope if o.top_relevant]


def load_eval_set(path: Path) -> list[EvalQuery]:
    """Read and validate the evaluation set.

    Args:
        path: JSON file with a list of queries.

    Returns:
        The queries.
    """
    adapter = TypeAdapter(list[EvalQuery])
    return adapter.validate_python(json.loads(path.read_text(encoding="utf-8")))


def first_relevant_rank(returned: Sequence[str], relevant: Sequence[str]) -> int | None:
    """Find the 1-based position of the first expected article.

    Args:
        returned: Article ids returned, best first.
        relevant: Expected article ids.

    Returns:
        The position, or None when no expected article was returned.
    """
    wanted = set(relevant)
    for position, document_id in enumerate(returned, start=1):
        if document_id in wanted:
            return position
    return None


def evaluate(
    name: str, queries: Sequence[EvalQuery], search: Callable[[str], SearchResponse]
) -> EvalReport:
    """Run every query through a search configuration.

    Args:
        name: Name of the configuration.
        queries: The evaluation set.
        search: Runs one query and returns at least `EVAL_TOP_K` results.

    Returns:
        The report.
    """
    report = EvalReport(name)
    for query in queries:
        response = search(query.query)
        returned = [result.document_id for result in response.results]
        # An empty answer to a re-ranked search counts as "not relevant": the
        # interfaces show nothing, which is the right outcome out of scope.
        if not response.reranked:
            top_relevant = None
        elif response.results:
            top_relevant = response.results[0].relevant
        else:
            top_relevant = False
        report.outcomes.append(
            QueryOutcome(
                query=query,
                rank=first_relevant_rank(returned, query.relevant),
                returned=returned,
                latency_ms=response.timings_ms.get("total", 0.0),
                top_relevant=top_relevant,
            )
        )
    return report


def _percent(value: float | None) -> str:
    """Format an optional share as a percentage ("—" when not measured)."""
    return "—" if value is None else f"{value:.0%}"


def markdown_table(reports: Sequence[EvalReport]) -> str:
    """Render the reports as a Markdown table.

    Args:
        reports: One report per configuration.

    Returns:
        The table.
    """
    lines = [
        "| Configuration | hit@1 | hit@5 | MRR@10 | Mean latency | Answers shown "
        "| Out of scope blocked |",
        "|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        lines.append(
            f"| {report.name} | {report.hit_at(1):.2f} | {report.hit_at(5):.2f} | "
            f"{report.mrr:.3f} | {report.mean_latency_ms / 1000:.2f} s | "
            f"{_percent(report.answers_shown)} | {_percent(report.out_of_scope_blocked)} |"
        )
    return "\n".join(lines)
