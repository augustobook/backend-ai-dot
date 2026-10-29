"""Tests of the LLM steps: OpenAI client wrapper, chunk enrichment and query rewriting."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openai
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.ingestion.chunker import Chunk
from app.llm.client import OpenAIStructuredLLM, build_llm, is_reasoning_model
from app.llm.enrichment import (
    ENRICHMENT_PROMPT_VERSION,
    ENRICHMENT_SYSTEM_PROMPT,
    EnrichmentCache,
    LLMEnricher,
    enrich_chunks,
    render_enrichment,
)
from app.llm.metadata import ChunkEnrichment, QueryAnalysis, clean_items
from app.llm.query_rewriter import LLMQueryRewriter
from tests.fakes import FakeEnricher, FakeStructuredLLM


def word_count(text: str) -> int:
    """Count tokens as whitespace-separated words, like the fake embedder."""
    return len(text.split())


class FakeCompletions:
    """Stands in for `client.chat.completions`, recording the request."""

    def __init__(self, parsed: Any = None, refusal: str | None = None, error: bool = False) -> None:
        self.kwargs: dict[str, Any] = {}
        self._parsed = parsed
        self._refusal = refusal
        self._error = error

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self._error:
            raise openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        message = SimpleNamespace(parsed=self._parsed, refusal=self._refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def fake_client(completions: FakeCompletions) -> Any:
    """Build an object shaped like `OpenAI` around the fake completions."""
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def make_chunk(document_id: str, position: int, text: str) -> Chunk:
    """Build a chunk with a predictable id."""
    return Chunk(chunk_id=position + 1, document_id=document_id, position=position, text=text)


# --- Client --------------------------------------------------------------------------------


def test_reasoning_models_get_effort_and_others_get_temperature() -> None:
    """gpt-5 / o-series reject temperature; the others are made deterministic."""
    answer = QueryAnalysis(
        rewritten_query="x",
        alternative_queries=[],
        similar_terms=[],
        categories=[],
        content_types=[],
    )
    assert is_reasoning_model("gpt-5-nano") and is_reasoning_model("o4-mini")
    assert not is_reasoning_model("gpt-4.1-nano")

    reasoning = FakeCompletions(parsed=answer)
    OpenAIStructuredLLM(fake_client(reasoning), "gpt-5-nano", "minimal").complete(
        "s", "u", QueryAnalysis
    )
    assert reasoning.kwargs["reasoning_effort"] == "minimal"
    assert "temperature" not in reasoning.kwargs
    assert reasoning.kwargs["response_format"] is QueryAnalysis

    classic = FakeCompletions(parsed=answer)
    OpenAIStructuredLLM(fake_client(classic), "gpt-4.1-nano", "minimal").complete(
        "s", "u", QueryAnalysis
    )
    assert classic.kwargs["temperature"] == 0
    assert "reasoning_effort" not in classic.kwargs


@pytest.mark.parametrize(
    "completions",
    [FakeCompletions(parsed=None, refusal="não posso"), FakeCompletions(error=True)],
)
def test_refusals_and_api_errors_become_llm_errors(completions: FakeCompletions) -> None:
    """The callers only handle `LLMError`, whatever went wrong underneath."""
    llm = OpenAIStructuredLLM(fake_client(completions), "gpt-5-nano")
    with pytest.raises(LLMError):
        llm.complete("s", "u", QueryAnalysis)


def test_build_llm_requires_a_key(settings: Settings) -> None:
    """Without OPENAI_API_KEY there is no client to build."""
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        build_llm(settings, "gpt-5-nano")
    keyed = settings.model_copy(update={"openai_api_key": SecretStr("sk-test")})
    assert build_llm(keyed, "gpt-5-nano").model_name == "gpt-5-nano"


def test_clean_items_strips_blanks_duplicates_and_extra_items() -> None:
    """Model output is normalized before it reaches the index."""
    assert clean_items(["  Prisão  de ventre ", "", "prisão de ventre", "a", "b"], 2) == [
        "Prisão de ventre",
        "a",
    ]


# --- Enrichment ----------------------------------------------------------------------------


def test_llm_enricher_sends_title_and_passage_and_cleans_the_answer() -> None:
    """The prompt carries the article title; repeated items are dropped."""
    llm = FakeStructuredLLM(
        {
            "context": "  Trata da   obstipação. ",
            "questions": ["Como soltar o intestino?", "como soltar o intestino?"],
            "similar_terms": ["prisão de ventre", " "],
            "content_types": ["diet", "diet", "treatment"],
        }
    )

    enrichment = LLMEnricher(llm).enrich("Obstipação", "A obstipação é...")

    assert "Artigo: Obstipação" in llm.calls[0][1]
    assert enrichment.context == "Trata da obstipação."
    assert enrichment.questions == ["Como soltar o intestino?"]
    assert enrichment.similar_terms == ["prisão de ventre"]
    assert enrichment.content_types == ["diet", "treatment"]


def test_render_enrichment_fits_the_token_budget() -> None:
    """Items are dropped from the longer list until the text fits."""
    enrichment = ChunkEnrichment(
        context="Contexto curto.",
        questions=["pergunta um?", "pergunta dois?", "pergunta três?"],
        similar_terms=["termo"],
        content_types=["other"],
    )

    full = render_enrichment(enrichment, word_count, 100)
    assert "Termos semelhantes: termo" in full and "pergunta três?" in full

    tight = render_enrichment(enrichment, word_count, 8)
    assert word_count(tight) <= 8
    assert tight.startswith("Contexto: Contexto curto.")
    assert render_enrichment(enrichment, word_count, 0) == ""


def test_enrich_chunks_uses_the_cache_on_the_next_run(tmp_path: Path) -> None:
    """A second ingestion pays nothing for chunks already enriched."""
    chunks = [
        make_chunk("nut-01", 0, "Fibras\n\nAs fibras..."),
        make_chunk("inf-01", 1, "Dengue\n\nA dengue..."),
    ]
    titles = {"nut-01": "Fibras na alimentação", "inf-01": "Dengue"}
    path = tmp_path / "cache.json"
    first = FakeEnricher()

    enriched = enrich_chunks(chunks, titles, first, EnrichmentCache(path), word_count, 200)

    assert sorted(first.calls) == ["Dengue", "Fibras na alimentação"]
    assert all(chunk.enrichment is not None and chunk.enrichment_text for chunk in enriched)
    assert "prisão de ventre" in enriched[0].search_text

    second = FakeEnricher()
    again = enrich_chunks(chunks, titles, second, EnrichmentCache(path), word_count, 200)
    assert second.calls == []
    assert again == enriched

    # Another model (or prompt version) is another cache key: it is asked again.
    other = FakeEnricher(model_name="other-model")
    enrich_chunks(chunks, titles, other, EnrichmentCache(path), word_count, 200)
    assert len(other.calls) == 2


def test_enrich_chunks_keeps_the_successes_when_some_calls_fail(tmp_path: Path) -> None:
    """The run fails, but what was paid for is cached for the retry."""
    chunks = [make_chunk("nut-01", 0, "Fibras\n\nA"), make_chunk("inf-01", 1, "Dengue\n\nB")]
    titles = {"nut-01": "Fibras na alimentação", "inf-01": "Dengue"}
    path = tmp_path / "cache.json"

    with pytest.raises(LLMError, match="1 chunks could not be enriched"):
        enrich_chunks(
            chunks, titles, FakeEnricher(fail_on={"Dengue"}), EnrichmentCache(path), word_count, 200
        )

    retry = FakeEnricher()
    enrich_chunks(chunks, titles, retry, EnrichmentCache(path), word_count, 200)
    assert retry.calls == ["Dengue"]


def test_unreadable_cache_is_ignored(tmp_path: Path) -> None:
    """A broken cache file costs a re-enrichment, never a crash."""
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")

    assert EnrichmentCache(path).get("anything") is None


# --- Query rewriting -----------------------------------------------------------------------


def test_query_rewriter_cleans_and_caches_per_query() -> None:
    """The same query (ignoring case and spaces) only calls the LLM once."""
    llm = FakeStructuredLLM(
        {
            "rewritten_query": "alimentação na constipação intestinal",
            "alternative_queries": [
                "o que comer para a prisão de ventre",
                "Alimentação na constipação intestinal",
                "quais alimentos soltam o intestino",
                "dieta para obstipação",
                "fibras para o intestino preso",
                "outra",
            ],
            "similar_terms": ["obstipação", "Obstipação", "constipação"],
            "categories": ["nutrition", "nutrition"],
            "content_types": ["diet"],
        }
    )
    rewriter = LLMQueryRewriter(llm)

    analysis = rewriter.analyze("o que comer para a prisão de ventre")
    again = rewriter.analyze("  O que comer para a  prisão de ventre ")

    assert again is analysis
    assert len(llm.calls) == 1
    assert analysis.similar_terms == ["obstipação", "constipação"]
    assert analysis.categories == ["nutrition"]
    # Variants equal to the query or to the rewrite are dropped; at most three are kept.
    assert analysis.alternative_queries == [
        "quais alimentos soltam o intestino",
        "dieta para obstipação",
        "fibras para o intestino preso",
    ]


def test_query_rewriter_cache_is_bounded() -> None:
    """The oldest query leaves the cache first."""
    llm = FakeStructuredLLM(
        {
            "rewritten_query": "",
            "alternative_queries": [],
            "similar_terms": [],
            "categories": [],
            "content_types": [],
        }
    )
    rewriter = LLMQueryRewriter(llm, cache_size=2)

    for query in ("a", "b", "c", "a"):
        result = rewriter.analyze(query)

    # An empty rewrite falls back to the query itself.
    assert result.rewritten_query == "a"
    assert len(llm.calls) == 4


def test_enrichment_prompt_asks_for_questions_that_name_their_subject() -> None:
    """Each question is embedded alone, so a generic one would match every article."""
    assert ENRICHMENT_PROMPT_VERSION == "2"
    assert "citar o assunto" in ENRICHMENT_SYSTEM_PROMPT
    assert "Quais são os sintomas?" in ENRICHMENT_SYSTEM_PROMPT
