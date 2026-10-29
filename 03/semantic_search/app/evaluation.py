"""Retrieval evaluation: how often the expected article comes back, and how high.

The evaluation set (`data/eval/queries.json`) holds questions written the way users
write them, each with the article(s) that answer it. A search is evaluated at the
article level, the level of the results:

- hit@1: the first result is an expected article;
- hit@5: an expected article is among the first five results (recall@5 when one
  relevant article per query is enough, which is how the set is written);
- MRR@10: mean of 1 / (position of the first expected article), 0 when it is not in
  the first ten. It rewards ranking the answer higher, not only finding it.

Comparing these numbers across configurations (BM25, dense, hybrid,
hybrid, re-ranking, rewrite...) is what tells whether a technique helps, instead of
judging it from a couple of hand-picked queries.
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
        kind: "lay" (popular words), "english" or "exact" (a literal term).
        query: The question, as a user would type it.
        relevant: Ids of the articles that answer it (any one counts as a hit).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    query: str
    relevant: list[str]


@dataclass(frozen=True)
class QueryOutcome:
    """Where the first expected article landed for one query.

    Attributes:
        query: The evaluated question.
        rank: 1-based position of the first expected article, None when absent.
        returned: Article ids returned, best first.
        latency_ms: Total search time.
    """

    query: EvalQuery
    rank: int | None
    returned: list[str]
    latency_ms: float


@dataclass
class EvalReport:
    """Aggregated metrics of one configuration over the evaluation set.

    Attributes:
        name: Name of the configuration.
        outcomes: One outcome per query.
    """

    name: str
    outcomes: list[QueryOutcome] = field(default_factory=list)

    def hit_at(self, k: int) -> float:
        """Share of queries whose expected article is in the first `k` results.

        Args:
            k: Cut-off.

        Returns:
            A value in [0, 1].
        """
        if not self.outcomes:
            return 0.0
        hits = sum(1 for outcome in self.outcomes if outcome.rank is not None and outcome.rank <= k)
        return hits / len(self.outcomes)

    @property
    def mrr(self) -> float:
        """Mean reciprocal rank over the first `EVAL_TOP_K` results.

        Returns:
            A value in [0, 1].
        """
        if not self.outcomes:
            return 0.0
        return statistics.fmean(
            1.0 / outcome.rank if outcome.rank is not None else 0.0 for outcome in self.outcomes
        )

    @property
    def mean_latency_ms(self) -> float:
        """Average search time.

        Returns:
            Milliseconds.
        """
        return statistics.fmean(o.latency_ms for o in self.outcomes) if self.outcomes else 0.0

    def misses(self, k: int = 5) -> list[QueryOutcome]:
        """Return the queries whose expected article is not in the first `k`.

        Args:
            k: Cut-off.

        Returns:
            The failed outcomes.
        """
        return [o for o in self.outcomes if o.rank is None or o.rank > k]


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
        report.outcomes.append(
            QueryOutcome(
                query=query,
                rank=first_relevant_rank(returned, query.relevant),
                returned=returned,
                latency_ms=response.timings_ms.get("total", 0.0),
            )
        )
    return report


def markdown_table(reports: Sequence[EvalReport]) -> str:
    """Render the reports as a Markdown table.

    Args:
        reports: One report per configuration.

    Returns:
        The table.
    """
    lines = [
        "| Configuration | hit@1 | hit@5 | MRR@10 | Mean latency |",
        "|---|---|---|---|---|",
    ]
    for report in reports:
        lines.append(
            f"| {report.name} | {report.hit_at(1):.2f} | {report.hit_at(5):.2f} | "
            f"{report.mrr:.3f} | {report.mean_latency_ms / 1000:.2f} s |"
        )
    return "\n".join(lines)
