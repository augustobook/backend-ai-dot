"""Evaluate search configurations on the evaluation set (`data/eval/queries.json`).

    uv run python scripts/evaluate.py                       # default configurations
    uv run python scripts/evaluate.py --configs bm25,hybrid,hybrid+rerank@30
    uv run python scripts/evaluate.py --list                # show every configuration

The models and the index are loaded once and shared by every configuration. The
configurations ending in "+rewrite" call the LLM and need OPENAI_API_KEY; they are
skipped without it. Re-ranked configurations are slow on CPU (one cross-encoder
pass per candidate and query).
"""

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import SearchMode, get_settings
from app.core.logging import configure_logging
from app.evaluation import EVAL_TOP_K, EvalReport, evaluate, load_eval_set, markdown_table
from app.services.artifacts import load_artifacts
from app.services.factory import build_embedder, build_query_rewriter, build_reranker
from app.services.results import SearchResponse
from app.services.search_service import SearchService

EVAL_SET = Path("data/eval/queries.json")


@dataclass(frozen=True)
class Config:
    """One search configuration to evaluate.

    Attributes:
        mode: Retrievers used.
        rerank: Re-rank with the cross-encoder.
        rewrite: Interpret the query with the LLM.
        overrides: Settings changed for this configuration.
    """

    mode: SearchMode
    rerank: bool = False
    rewrite: bool = False
    overrides: dict[str, Any] = field(default_factory=dict)


CONFIGS: dict[str, Config] = {
    "bm25": Config("keyword"),
    "semantic": Config("semantic"),
    "hybrid": Config("hybrid"),
    "hybrid-dense-x2": Config("hybrid", overrides={"rrf_dense_weight": 2.0}),
    "hybrid-bm25-x2": Config("hybrid", overrides={"rrf_keyword_weight": 2.0}),
    "hybrid+rerank@10": Config("hybrid", rerank=True, overrides={"rerank_candidates": 10}),
    "hybrid+rerank@20": Config("hybrid", rerank=True, overrides={"rerank_candidates": 20}),
    "hybrid+rerank@30": Config("hybrid", rerank=True, overrides={"rerank_candidates": 30}),
    "hybrid+rewrite": Config("hybrid", rewrite=True),
    "hybrid+rewrite+rerank@20": Config(
        "hybrid", rerank=True, rewrite=True, overrides={"rerank_candidates": 20}
    ),
}
DEFAULT_CONFIGS = [name for name in CONFIGS if "rerank" not in name and "rewrite" not in name]


def _searcher(service: SearchService, config: Config) -> Callable[[str], SearchResponse]:
    """Bind a service and a configuration into a one-argument search.

    Args:
        service: The search service of the configuration.
        config: The configuration.

    Returns:
        A function that searches one query.
    """

    def search(query: str) -> SearchResponse:
        return service.search(
            query, top_k=EVAL_TOP_K, mode=config.mode, rerank=config.rerank, rewrite=config.rewrite
        )

    return search


def main() -> int:
    """Run the requested configurations and print a table of metrics.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Evaluate search configurations.")
    parser.add_argument(
        "--configs",
        default=",".join(DEFAULT_CONFIGS),
        help="Comma-separated configuration names (see --list).",
    )
    parser.add_argument("--list", action="store_true", help="List the configurations.")
    parser.add_argument("--misses", action="store_true", help="Print the queries missed at 5.")
    args = parser.parse_args()

    if args.list:
        for name, config in CONFIGS.items():
            print(f"{name:28} {config}")
        return 0

    names = [name.strip() for name in args.configs.split(",") if name.strip()]
    unknown = [name for name in names if name not in CONFIGS]
    if unknown:
        print(f"Unknown configurations: {', '.join(unknown)} (see --list)")
        return 1

    settings = get_settings()
    configure_logging("WARNING")
    logging.getLogger("app").setLevel(logging.WARNING)
    queries = load_eval_set(EVAL_SET)
    artifacts = load_artifacts(settings.storage_dir)
    embedder = build_embedder(settings)
    needs_rerank = any(CONFIGS[name].rerank for name in names)
    reranker = build_reranker(settings) if needs_rerank else None
    rewriter = (
        build_query_rewriter(settings) if any(CONFIGS[name].rewrite for name in names) else None
    )
    print(
        f"{len(queries)} queries; index: {artifacts.manifest.document_count} articles, "
        f"{artifacts.manifest.chunk_count} chunks, enrichment: "
        f"{artifacts.manifest.enrichment_model or 'none'}"
    )

    reports: list[EvalReport] = []
    for name in names:
        config = CONFIGS[name]
        if config.rewrite and rewriter is None:
            print(f"skip {name}: needs OPENAI_API_KEY")
            continue
        service = SearchService(
            embedder=embedder,
            artifacts=artifacts,
            settings=settings.model_copy(update=config.overrides),
            reranker=reranker if config.rerank else None,
            query_rewriter=rewriter if config.rewrite else None,
        )
        started = time.perf_counter()
        report = evaluate(name, queries, _searcher(service, config))
        reports.append(report)
        print(
            f"done {name}: hit@5={report.hit_at(5):.2f} MRR={report.mrr:.3f} "
            f"({time.perf_counter() - started:.0f}s)",
            flush=True,
        )
        if args.misses:
            for outcome in report.misses():
                print(
                    f"   miss {outcome.query.id} '{outcome.query.query}' -> rank {outcome.rank}, "
                    f"expected {outcome.query.relevant}, got {outcome.returned[:3]}"
                )

    print()
    print(markdown_table(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
