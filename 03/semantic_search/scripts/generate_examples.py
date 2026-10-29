"""Generate `docs/EXAMPLES.md` with real queries and the results the search returned.

Run with:  uv run python scripts/generate_examples.py

Every query is searched twice:
- pure semantic search (embeddings + FAISS, query as typed), the minimum the
  assignment asks for;
- the default pipeline (hybrid + cross-encoder).

The LLM rewrite of the query is off in both, as in the evaluation: its output
varies between runs, and the examples must be reproducible and match the metrics
in the README. The ingestion enrichment is already in the versioned index, so no
API key is needed.

The expected articles come from the evaluation set, so each result is marked as a
hit or not. The document is written in Portuguese, like the rest of `docs/`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import SemanticSearchError
from app.core.logging import configure_logging
from app.evaluation import EvalQuery, load_eval_set
from app.services.factory import build_search_service
from app.services.results import SearchResponse, SearchResult
from app.services.search_service import SearchService

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "docs" / "EXAMPLES.md"
EVAL_SET = ROOT / "data" / "eval" / "queries.json"

TOP_K = 3
SNIPPET_CHARS = 280


@dataclass(frozen=True, slots=True)
class Example:
    """A query shown in the document.

    Attributes:
        title: Section title.
        note: What the example demonstrates.
        query: Text searched.
        relevant: Ids of the articles that answer it (empty: nothing should match).
    """

    title: str
    note: str
    query: str
    relevant: tuple[str, ...]


# (eval set id, title, note). The query and the expected articles are read from the
# evaluation set, so the examples cannot drift from what the metrics measure.
EVAL_EXAMPLES: tuple[tuple[str, str, str], ...] = (
    (
        "q01",
        "Palavras populares vs. termo técnico",
        'O usuário diz "prisão de ventre"; o artigo fala em "obstipação".',
    ),
    ("q02", "Pergunta direta", "Pergunta curta, do jeito que se digita num buscador."),
    (
        "q03",
        "Sintoma descrito sem o nome da doença",
        "Nenhuma palavra da pergunta aparece no nome do artigo.",
    ),
    (
        "q09",
        "Sintomas que apontam um diagnóstico",
        "A busca precisa ligar a descrição dos sintomas à doença.",
    ),
    (
        "q04",
        "Pergunta em inglês",
        "O modelo de embeddings é multilíngue: a pergunta em inglês acha artigos em português.",
    ),
    (
        "q05",
        "Termo exato",
        "Um nome científico, caso em que a busca por palavras-chave ajuda a semântica.",
    ),
)

OUT_OF_SCOPE = Example(
    title="Assunto fora do acervo",
    note=(
        "Nenhum artigo responde. A busca semântica sempre devolve os vizinhos mais "
        "próximos; o cross-encoder é que diz que nenhum resultado é confiável."
    ),
    query="como trocar o óleo do carro",
    relevant=(),
)


def load_examples() -> list[Example]:
    """Build the example list from the evaluation set.

    Returns:
        The examples, in the order they appear in the document.
    """
    by_id: dict[str, EvalQuery] = {query.id: query for query in load_eval_set(EVAL_SET)}
    examples = [
        Example(title, note, by_id[query_id].query, tuple(by_id[query_id].relevant))
        for query_id, title, note in EVAL_EXAMPLES
    ]
    return [*examples, OUT_OF_SCOPE]


def run_examples(
    service: SearchService, examples: list[Example]
) -> list[tuple[Example, SearchResponse, SearchResponse]]:
    """Search every example with both pipelines.

    Args:
        service: Loaded search service.
        examples: Queries to search.

    Returns:
        Each example with its semantic and default responses.
    """
    results = []
    for index, example in enumerate(examples, start=1):
        print(f"[{index}/{len(examples)}] {example.query}", flush=True)
        semantic = service.search(
            example.query, top_k=TOP_K, mode="semantic", rerank=False, rewrite=False
        )
        default = service.search(example.query, top_k=TOP_K, rewrite=False)
        results.append((example, semantic, default))
    return results


def _snippet(text: str) -> str:
    """Shorten a chunk, dropping the title line added to every chunk.

    Args:
        text: Chunk text.

    Returns:
        At most SNIPPET_CHARS characters of the passage, on one line.
    """
    passage = " ".join(text.split("\n\n", 1)[-1].split())
    return passage if len(passage) <= SNIPPET_CHARS else f"{passage[:SNIPPET_CHARS].rstrip()}…"


def _hit_mark(result: SearchResult, example: Example) -> str:
    """Mark a result as an expected article or not.

    Args:
        result: A search result.
        example: The example it answers.

    Returns:
        ✅ for an expected article, an empty string otherwise.
    """
    return "✅" if result.document_id in example.relevant else ""


def _results_table(response: SearchResponse, example: Example, score_label: str) -> list[str]:
    """Render the results of one pipeline as a Markdown table.

    Args:
        response: The search response.
        example: The example searched.
        score_label: Header of the score column.

    Returns:
        The Markdown lines.
    """
    if not response.results:
        return ["Nenhum resultado.", ""]
    lines = [
        f"| # | Artigo | Categoria | {score_label} | Esperado |",
        "|---|---|---|---|---|",
    ]
    for result in response.results:
        low = " *(baixa relevância)*" if result.relevant is False else ""
        lines.append(
            f"| {result.rank} | {result.title} (`{result.document_id}`){low} | "
            f"{result.category} | {result.score:.3f} | {_hit_mark(result, example)} |"
        )
    lines.append("")
    return lines


def render_markdown(
    results: list[tuple[Example, SearchResponse, SearchResponse]], settings: Settings
) -> str:
    """Render the collected results as Markdown.

    Args:
        results: Output of `run_examples`.
        settings: Settings used (the models are recorded in the document).

    Returns:
        The content of `docs/EXAMPLES.md`.
    """
    lines = [
        "# Exemplos de consultas e resultados",
        "",
        "Resultados reais gerados por `uv run python scripts/generate_examples.py`, sobre o",
        "índice versionado em `storage/`. Cada consulta foi buscada de duas formas:",
        "",
        "- **Busca semântica pura:** só embeddings e FAISS, com a pergunta como foi digitada.",
        "  A nota é a similaridade de cosseno entre a pergunta e o melhor trecho do artigo.",
        "- **Pipeline padrão:** busca híbrida (embeddings + BM25), reordenada pelo",
        "  cross-encoder. A nota é a relevância do cross-encoder, entre 0 e 1.",
        "",
        "Nas duas, a reescrita da pergunta pela LLM fica desligada, como na avaliação: ela",
        "varia de uma execução para outra, e os exemplos precisam ser reproduzíveis. O",
        "enriquecimento dos trechos feito pela LLM na ingestão já está no índice.",
        "",
        "A coluna **Esperado** marca os artigos que respondem à pergunta, segundo o conjunto",
        "de avaliação ([data/eval/queries.json](../data/eval/queries.json)).",
        "",
        f"- Modelo de embeddings: `{settings.embedding_model_name}`",
        f"- Cross-encoder: `{settings.reranker_model_name}`",
        "",
    ]
    for index, (example, semantic, default) in enumerate(results, start=1):
        lines += [f"## {index}. {example.title}", "", f"> {example.note}", ""]
        lines += [f"**Consulta:** `{example.query}`", ""]
        lines += ["**Busca semântica pura**", ""]
        lines += _results_table(semantic, example, "Cosseno")
        lines += ["**Pipeline padrão**", ""]
        lines += _results_table(default, example, "Relevância")
        if default.results and all(result.relevant is False for result in default.results):
            lines += [
                "Nenhum resultado passou do limite de relevância: a interface mostra o aviso",
                '"nenhum resultado confiável" em vez de apresentar esses artigos como resposta.',
                "",
            ]
        elif default.results:
            best = default.results[0]
            lines += [
                f"Trecho do 1º resultado ({best.title}):",
                "",
                f"> {_snippet(best.chunk_text)}",
                "",
            ]
        lines += ["---", ""]
    lines += [
        "## O que os exemplos mostram",
        "",
        "- **O cosseno não separa acerto de erro.** Na busca semântica pura, todas as notas",
        '  ficam entre 0.82 e 0.90, inclusive em "como trocar o óleo do carro" (caso 7).',
        '  Nenhum corte de cosseno consegue dizer "nenhum artigo responde".',
        "- **O cross-encoder separa.** Fora do acervo, as notas caem para perto de zero e a",
        "  interface avisa que não há resultado confiável. Ele também corrige a ordem: no",
        "  caso 4, o infarto sobe do 3º para o 1º lugar.",
        "- **Ele também erra.** No caso 1, Osteoporose fica à frente de Obstipação por falar",
        "  de dieta. No caso 3, o artigo certo aparece, mas abaixo do limite, e a pergunta",
        "  fica sem resposta. Nos dois, a busca semântica pura acertou o 1º lugar.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Generate the examples file.

    Returns:
        The process exit code.
    """
    settings = get_settings()
    configure_logging("WARNING")
    logging.getLogger("app").setLevel(logging.WARNING)

    try:
        service = build_search_service(settings)
        results = run_examples(service, load_examples())
    except SemanticSearchError as exc:
        print(f"Could not generate the examples: {exc}")
        return 1

    OUTPUT_PATH.write_text(render_markdown(results, settings), encoding="utf-8")
    print(f"Examples written to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
