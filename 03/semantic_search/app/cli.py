"""Command-line interface: `ingest`, `search` and `stats`.

Every command delegates to the services; this module only parses arguments and
renders the results with rich.

    uv run python -m app.cli ingest [--force]
    uv run python -m app.cli search "como melhorar o sono" [--mode hybrid] [--compare]
    uv run python -m app.cli stats
"""

from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from app.core.config import SearchMode, get_settings
from app.core.exceptions import SemanticSearchError
from app.core.logging import configure_logging
from app.services.artifacts import read_manifest
from app.services.factory import build_indexing_service, build_search_service
from app.services.indexing_service import IngestionStage
from app.services.results import SearchResponse
from app.services.search_service import SearchService

app = typer.Typer(
    help="Hybrid semantic search over Portuguese health articles.", no_args_is_help=True
)
console = Console()

SNIPPET_CHARS = 160

INGESTION_STAGE_LABELS: dict[IngestionStage, str] = {
    "enrich": "Enriching chunks (LLM)",
    "embed": "Embedding chunks",
    "questions": "Embedding questions",
}

# The four pipelines shown side by side by `search --compare`.
COMPARED_PIPELINES: list[tuple[str, SearchMode, bool]] = [
    ("BM25", "keyword", False),
    ("Semantic", "semantic", False),
    ("Hybrid", "hybrid", False),
    ("Hybrid + rerank", "hybrid", True),
]


@app.callback()
def main() -> None:
    """Configure logging before any command runs."""
    configure_logging(get_settings().log_level)


@app.command()
def ingest(
    force: Annotated[
        bool, typer.Option("--force", help="Rebuild even if nothing changed.")
    ] = False,
) -> None:
    """Build the index: load, chunk, embed and store the documents."""
    service = build_indexing_service(get_settings())
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        tasks: dict[str, TaskID] = {}

        def on_progress(stage: IngestionStage, done: int, total: int) -> None:
            if stage not in tasks:
                tasks[stage] = progress.add_task(INGESTION_STAGE_LABELS[stage], total=total)
            progress.update(tasks[stage], completed=done, total=total)

        try:
            report = service.ingest(force=force, progress=on_progress)
        except SemanticSearchError as exc:
            console.print(f"[red]Ingestion failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    manifest = report.manifest
    if report.skipped:
        console.print(
            "[yellow]Index already up to date[/yellow] (same dataset and settings). "
            "Use --force to rebuild."
        )
    else:
        console.print(
            f"[green]Indexed[/green] {manifest.document_count} documents as "
            f"{manifest.chunk_count} chunks in {report.duration_seconds:.1f}s."
        )
        if manifest.enrichment_model:
            console.print(
                f"Chunks enriched by {manifest.enrichment_model}; "
                f"{manifest.question_count} generated questions indexed."
            )
        else:
            console.print(
                "[yellow]Chunks indexed without LLM enrichment[/yellow] "
                "(set OPENAI_API_KEY and ENRICHMENT_ENABLED=true to enable it)."
            )


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search text.")],
    top_k: Annotated[int | None, typer.Option("--top-k", "-k", help="Documents to return.")] = None,
    mode: Annotated[
        str | None, typer.Option(help="hybrid, semantic or keyword (default: configured).")
    ] = None,
    no_rerank: Annotated[
        bool, typer.Option("--no-rerank", help="Skip the cross-encoder re-ranking.")
    ] = False,
    no_rewrite: Annotated[
        bool, typer.Option("--no-rewrite", help="Search the query as typed (no LLM rewrite).")
    ] = False,
    min_score: Annotated[float | None, typer.Option(help="Minimum final score (0-1).")] = None,
    category: Annotated[str | None, typer.Option(help="Only search this category.")] = None,
    compare: Annotated[
        bool, typer.Option("--compare", help="Show BM25, semantic, hybrid and reranked results.")
    ] = False,
) -> None:
    """Search the documents most relevant to a query."""
    try:
        service = build_search_service(get_settings())
        rewrite = False if no_rewrite else None
        if compare:
            _print_comparison(service, query, top_k, min_score, category, rewrite)
            return
        response = service.search(
            query,
            top_k=top_k,
            mode=mode,
            rerank=False if no_rerank else None,
            min_score=min_score,
            category=category,
            rewrite=rewrite,
        )
    except SemanticSearchError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    _print_results(response)


@app.command()
def stats() -> None:
    """Show how the index was built."""
    settings = get_settings()
    try:
        manifest = read_manifest(settings.storage_dir)
    except SemanticSearchError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if manifest is None:
        console.print("[yellow]No index yet.[/yellow] Run: uv run python -m app.cli ingest")
        raise typer.Exit(code=1)

    table = Table(title="Index", show_header=False)
    for key, value in manifest.model_dump().items():
        table.add_row(key.replace("_", " "), str(value))
    console.print(table)


def _print_results(response: SearchResponse) -> None:
    """Render a search response as a table.

    Args:
        response: Results to show.
    """
    title = (
        f"{response.mode}{' + rerank' if response.reranked else ''} | "
        f"{response.timings_ms.get('total', 0):.0f} ms"
    )
    _print_analysis(response)
    table = Table(title=f"[bold]{response.query}[/bold]  ({title})")
    table.add_column("#", justify="right")
    table.add_column("Document")
    table.add_column("Category")
    table.add_column("Score", justify="right")
    table.add_column("Matched passage")
    for result in response.results:
        low = " [yellow](low relevance)[/yellow]" if result.relevant is False else ""
        table.add_row(
            str(result.rank),
            f"{result.title}{low}\n[dim]{result.document_id}[/dim]",
            result.category,
            f"{result.score:.3f}",
            _snippet(result.chunk_text),
        )
    if not response.results:
        console.print("[yellow]No results.[/yellow]")
    elif all(result.relevant is False for result in response.results):
        console.print(
            "[yellow]No confident result:[/yellow] every document is below the relevance "
            "threshold; the collection may not cover this subject."
        )
    console.print(table)


def _print_comparison(
    service: SearchService,
    query: str,
    top_k: int | None,
    min_score: float | None,
    category: str | None,
    rewrite: bool | None,
) -> None:
    """Run the four pipelines and show their rankings side by side.

    Args:
        service: Loaded search service.
        query: Search text.
        top_k: Documents per pipeline.
        min_score: Minimum final score.
        category: Category filter.
        rewrite: Interpret the query with the LLM (None: when configured).
    """
    table = Table(title=f"[bold]{query}[/bold]")
    table.add_column("#", justify="right")
    columns = []
    for index, (label, mode, rerank) in enumerate(COMPARED_PIPELINES):
        response = service.search(
            query,
            top_k=top_k,
            mode=mode,
            rerank=rerank,
            min_score=min_score,
            category=category,
            rewrite=rewrite,
        )
        if index == 0:
            _print_analysis(response)
        table.add_column(f"{label}\n[dim]{response.timings_ms.get('total', 0):.0f} ms[/dim]")
        columns.append(
            [
                f"{result.title} [dim]({result.score:.2f})[/dim]"
                + (" [yellow]low[/yellow]" if result.relevant is False else "")
                for result in response.results
            ]
        )
    for index in range(max((len(column) for column in columns), default=0)):
        table.add_row(
            str(index + 1), *(column[index] if index < len(column) else "" for column in columns)
        )
    console.print(table)


def _print_analysis(response: SearchResponse) -> None:
    """Show how the LLM understood the query, when it was rewritten.

    Args:
        response: A search response.
    """
    analysis = response.analysis
    if analysis is None:
        return
    console.print(f"[dim]Rewritten:[/dim] {analysis.rewritten_query}")
    details: list[tuple[str, list[str]]] = [
        ("Also searched as", analysis.alternative_queries),
        ("Similar terms", analysis.similar_terms),
        ("Categories", list(analysis.categories)),
        ("Content types", list(analysis.content_types)),
    ]
    for label, values in details:
        if values:
            console.print(f"[dim]{label}:[/dim] {', '.join(values)}")


def _snippet(text: str) -> str:
    """Shorten a chunk for the table, dropping the title line added to every chunk.

    Args:
        text: Chunk text.

    Returns:
        At most SNIPPET_CHARS characters of the passage.
    """
    passage = text.split("\n\n", 1)[-1].replace("\n", " ")
    return passage if len(passage) <= SNIPPET_CHARS else f"{passage[:SNIPPET_CHARS].rstrip()}…"


if __name__ == "__main__":
    app()
