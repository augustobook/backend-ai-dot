"""Chunk enrichment: the LLM writes, once per chunk, what a user would search for.

Why: the articles use technical vocabulary ("obstipação", "hipertensão arterial"),
while users write as they speak ("prisão de ventre", "pressão alta"). Neither BM25
nor a small embedding model bridges that gap reliably. Asking an LLM, at ingestion,
for the questions each passage answers and for the popular names of its concepts
puts the users' vocabulary into the index:

- the context, similar terms and questions are appended to the chunk text that is
  embedded, indexed by BM25 and read by the cross-encoder;
- each question is also embedded on its own (see `DenseRetriever`), so a query is
  compared with questions, which is much closer than a question vs. a paragraph.

The LLM runs once per chunk and the answers are cached on disk by
(model, prompt version, chunk text): re-running the ingestion, or changing an
unrelated setting, never pays twice for the same chunk.
"""

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol

from app.core.exceptions import LLMError
from app.ingestion.chunker import PARAGRAPH_SEPARATOR, Chunk, TokenCounter
from app.llm.client import StructuredLLM
from app.llm.metadata import MAX_QUESTIONS, MAX_SIMILAR_TERMS, ChunkEnrichment, clean_items

logger = logging.getLogger(__name__)

# Bump when the prompt or the schema changes: cached answers of an older version are
# then ignored and the manifest marks the index as outdated.
# v2: questions must name their subject. Each question is embedded on its own, without
# the chunk around it, so "Quais são os sintomas?" from Dengue and from Gripe got the
# same vector (cosine 0.929 for both against "quais os sintomas da dengue?"), and
# generic questions of many articles crowded the top of the dense ranking. Naming the
# subject separated them (0.985 vs. 0.919).
ENRICHMENT_PROMPT_VERSION = "2"

ENRICHMENT_SYSTEM_PROMPT = f"""\
Você prepara trechos de artigos de saúde da Wikipédia para um buscador.
Para o trecho recebido, responda em português do Brasil:

- context: uma ou duas frases que situam o trecho no artigo (de que doença ou tema
  ele fala e que aspecto aborda). Não repita o trecho.
- questions: de 3 a {MAX_QUESTIONS} perguntas que uma pessoa leiga faria e que o trecho
  responde, escritas como ela escreveria (linguagem simples, termos populares).
  Só perguntas que o trecho realmente responde.
  Cada pergunta será lida sozinha, sem o trecho: ela precisa citar o assunto pelo
  nome, de preferência o popular e o técnico quando houver. Nunca use "isso",
  "a doença", "esse problema" ou perguntas genéricas como "Quais são os sintomas?".
  Ex.: "Quais são os sintomas da dengue?", "O que comer para aliviar a prisão de
  ventre (constipação)?".
- similar_terms: até {MAX_SIMILAR_TERMS} sinônimos, nomes populares e termos técnicos
  equivalentes dos conceitos centrais do trecho (ex.: "prisão de ventre" para
  "constipação intestinal", "pressão alta" para "hipertensão"). Não repita palavras
  que já estão no trecho.
- content_types: os tipos de informação do trecho, entre: definition, symptoms,
  causes, risk-factors, diagnosis, treatment, prevention, diet, epidemiology,
  history, other.

Use apenas o que está no trecho; não acrescente fatos médicos."""

EnrichmentProgress = Callable[[int], None]
"""Called with the number of chunks enriched since the previous call."""


class Enricher(Protocol):
    """Produces the enrichment of one chunk.

    Attributes:
        model_name: Model that writes the enrichment (stored in the manifest).
        prompt_version: Version of the prompt (stored in the manifest and cache key).
    """

    model_name: str
    prompt_version: str

    def enrich(self, title: str, passage: str) -> ChunkEnrichment:
        """Enrich one passage.

        Args:
            title: Title of the article the passage comes from.
            passage: Text of the passage.

        Returns:
            The enrichment.

        Raises:
            LLMError: If the model could not answer.
        """
        ...


class LLMEnricher:
    """`Enricher` that asks a structured LLM.

    Args:
        llm: The model client.
    """

    prompt_version = ENRICHMENT_PROMPT_VERSION

    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm
        self.model_name = llm.model_name

    def enrich(self, title: str, passage: str) -> ChunkEnrichment:
        """Enrich one passage.

        Args:
            title: Title of the article the passage comes from.
            passage: Text of the passage.

        Returns:
            The enrichment, with blank and repeated items removed.

        Raises:
            LLMError: If the model could not answer.
        """
        answer = self._llm.complete(
            ENRICHMENT_SYSTEM_PROMPT,
            f"Artigo: {title}\n\nTrecho:\n{passage}",
            ChunkEnrichment,
        )
        return ChunkEnrichment(
            context=" ".join(answer.context.split()),
            questions=clean_items(answer.questions, MAX_QUESTIONS),
            similar_terms=clean_items(answer.similar_terms, MAX_SIMILAR_TERMS),
            content_types=list(dict.fromkeys(answer.content_types)),
        )


class EnrichmentCache:
    """Enrichments already paid for, in a JSON file keyed by model, prompt and text.

    Args:
        path: The JSON file (created on the first save).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: dict[str, ChunkEnrichment] = {}
        self._lock = threading.Lock()
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._entries = {
                    key: ChunkEnrichment.model_validate(value) for key, value in raw.items()
                }
            except (json.JSONDecodeError, ValueError, AttributeError) as exc:
                logger.warning("Ignoring unreadable enrichment cache %s: %s", path, exc)

    @staticmethod
    def key(enricher: Enricher, text: str) -> str:
        """Build the cache key of a chunk.

        Args:
            enricher: The enricher (its model and prompt version are part of the key).
            text: Text of the chunk.

        Returns:
            A SHA-256 hex digest.
        """
        payload = f"{enricher.model_name}\n{enricher.prompt_version}\n{text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> ChunkEnrichment | None:
        """Return a cached enrichment.

        Args:
            key: Cache key.

        Returns:
            The enrichment, or None when it was never computed.
        """
        return self._entries.get(key)

    def put(self, key: str, enrichment: ChunkEnrichment) -> None:
        """Store an enrichment in memory (call `save` to persist).

        Args:
            key: Cache key.
            enrichment: The enrichment.
        """
        with self._lock:
            self._entries[key] = enrichment

    def save(self) -> None:
        """Write the cache to disk, sorted so the file diffs well."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: self._entries[key].model_dump() for key in sorted(self._entries)}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def enrich_chunks(
    chunks: Sequence[Chunk],
    titles: dict[str, str],
    enricher: Enricher,
    cache: EnrichmentCache,
    count_tokens: TokenCounter,
    max_tokens: int,
    concurrency: int = 8,
    progress: EnrichmentProgress | None = None,
) -> list[Chunk]:
    """Enrich every chunk, reusing the cache and calling the LLM in parallel.

    The cache is saved even when some calls fail, so a new run only pays for the
    chunks that are still missing.

    Args:
        chunks: Chunks to enrich.
        titles: Document id -> title.
        enricher: The enricher.
        cache: Enrichments already computed.
        count_tokens: Tokenizer of the embedding model (for the token budget).
        max_tokens: Budget of the text appended to each chunk.
        concurrency: Parallel LLM calls.
        progress: Optional callback receiving how many chunks were enriched.

    Returns:
        The chunks with their enrichment, in the same order.

    Raises:
        LLMError: If some chunks could not be enriched (after the client's retries).
    """
    results: dict[int, ChunkEnrichment] = {}
    missing: list[tuple[Chunk, str]] = []
    for chunk in chunks:
        key = EnrichmentCache.key(enricher, chunk.text)
        cached = cache.get(key)
        if cached is None:
            missing.append((chunk, key))
        else:
            results[chunk.chunk_id] = cached
    if progress is not None and results:
        progress(len(results))
    logger.info("Enrichment: %d cached, %d to request", len(results), len(missing))

    failures: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(enricher.enrich, titles[chunk.document_id], _passage(chunk, titles)): (
                    chunk,
                    key,
                )
                for chunk, key in missing
            }
            for future in as_completed(futures):
                chunk, key = futures[future]
                try:
                    enrichment = future.result()
                except LLMError as exc:
                    failures.append(f"{chunk.document_id}#{chunk.position}: {exc}")
                    continue
                cache.put(key, enrichment)
                results[chunk.chunk_id] = enrichment
                if progress is not None:
                    progress(1)
    finally:
        if missing:
            cache.save()

    if failures:
        raise LLMError(
            f"{len(failures)} chunks could not be enriched (the others were cached; run "
            f"the ingestion again to retry). First error: {failures[0]}"
        )
    return [
        chunk.model_copy(
            update={
                "enrichment": results[chunk.chunk_id],
                "enrichment_text": render_enrichment(
                    results[chunk.chunk_id], count_tokens, max_tokens
                ),
            }
        )
        for chunk in chunks
    ]


def render_enrichment(
    enrichment: ChunkEnrichment, count_tokens: TokenCounter, max_tokens: int
) -> str:
    """Write the enrichment as text to append to the chunk, within a token budget.

    When it does not fit, the last item of the longer list (similar terms or
    questions) is dropped until it does; the context goes last. The questions dropped
    here are still embedded on their own, so nothing is lost for the dense search.

    Args:
        enrichment: The enrichment.
        count_tokens: Tokenizer of the embedding model.
        max_tokens: Budget, in tokens.

    Returns:
        The text (empty when nothing fits).
    """
    context = enrichment.context
    terms = list(enrichment.similar_terms)
    questions = list(enrichment.questions)
    while True:
        lines = []
        if context:
            lines.append(f"Contexto: {context}")
        if terms:
            lines.append(f"Termos semelhantes: {'; '.join(terms)}")
        if questions:
            lines.append(f"Perguntas: {' '.join(questions)}")
        text = "\n".join(lines)
        if not text or count_tokens(text) <= max_tokens:
            return text
        if terms or questions:
            (terms if len(terms) >= len(questions) else questions).pop()
        else:
            context = ""


def _passage(chunk: Chunk, titles: dict[str, str]) -> str:
    """Return the chunk without the title the chunker prepended (sent separately).

    Args:
        chunk: A chunk.
        titles: Document id -> title.

    Returns:
        The passage.
    """
    return chunk.text.removeprefix(f"{titles[chunk.document_id]}{PARAGRAPH_SEPARATOR}")
