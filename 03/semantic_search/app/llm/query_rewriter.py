"""Query rewriting: the LLM translates the user's words into the articles' words.

Before the search, the query goes to the LLM, which returns:
- the query rewritten in the vocabulary of an encyclopedic article;
- a few alternative formulations of the same question (multi-query): every one of
  them is searched, so a single bad rewrite cannot steer the whole search;
- similar terms (technical and popular names) that BM25 can match;
- the categories and content types it is probably about, which give a *soft* boost
  to matching chunks (never a hard filter: a wrong guess must not hide the answer).

The answers are kept in a small in-memory LRU cache: the comparison view runs the
same query through four pipelines, and toggling a control re-runs a search, which
must not pay (in time and money) for the same rewrite again.
"""

import logging
import threading
from collections import OrderedDict
from typing import Protocol

from app.llm.client import StructuredLLM
from app.llm.metadata import (
    MAX_ALTERNATIVE_QUERIES,
    MAX_SIMILAR_TERMS,
    QueryAnalysis,
    clean_items,
)

logger = logging.getLogger(__name__)

CACHE_SIZE = 256

QUERY_REWRITE_SYSTEM_PROMPT = f"""\
Você ajuda um buscador de artigos de saúde da Wikipédia em português.
Para a pergunta do usuário, responda:

- rewritten_query: a pergunta reescrita com o vocabulário de um artigo
  enciclopédico (nomes técnicos no lugar de populares, sem perder o que foi pedido),
  em português, mesmo que a pergunta venha em outra língua.
- alternative_queries: de 2 a {MAX_ALTERNATIVE_QUERIES} outras formas de fazer a mesma
  pergunta, em português, cada uma por um caminho diferente (com palavras populares,
  com termos técnicos, pelo sintoma ou pela causa). Todas pedem a mesma coisa que a
  original e citam o assunto pelo nome.
- similar_terms: até {MAX_SIMILAR_TERMS} sinônimos, nomes técnicos e populares do que
  foi perguntado (ex.: "prisão de ventre" -> "constipação intestinal", "obstipação").
- categories: as categorias que provavelmente têm a resposta (pode ser vazia):
  nutrition (alimentação, vitaminas, digestão), mental-health (saúde mental),
  sleep-exercise (sono e atividade física), chronic-diseases (doenças crônicas),
  infectious-diseases (doenças infecciosas e prevenção).
- content_types: o tipo de informação pedida (pode ser vazia), entre: definition,
  symptoms, causes, risk-factors, diagnosis, treatment, prevention, diet,
  epidemiology, history, other.

Não responda a pergunta; só a interprete."""


class QueryRewriter(Protocol):
    """Interprets a query before the search.

    Attributes:
        model_name: Model used (shown in the interface).
    """

    model_name: str

    def analyze(self, query: str) -> QueryAnalysis:
        """Rewrite a query and extract its metadata.

        Args:
            query: The user's query.

        Returns:
            The analysis.

        Raises:
            LLMError: If the model could not answer.
        """
        ...


class LLMQueryRewriter:
    """`QueryRewriter` that asks a structured LLM, with an LRU cache.

    Args:
        llm: The model client.
        cache_size: Queries kept in memory.
    """

    def __init__(self, llm: StructuredLLM, cache_size: int = CACHE_SIZE) -> None:
        self._llm = llm
        self.model_name = llm.model_name
        self._cache: OrderedDict[str, QueryAnalysis] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def analyze(self, query: str) -> QueryAnalysis:
        """Rewrite a query and extract its metadata (cached per query text).

        Args:
            query: The user's query.

        Returns:
            The analysis, with blank and repeated items removed.

        Raises:
            LLMError: If the model could not answer.
        """
        key = " ".join(query.lower().split())
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        answer = self._llm.complete(QUERY_REWRITE_SYSTEM_PROMPT, query, QueryAnalysis)
        rewritten = " ".join(answer.rewritten_query.split()) or query
        # Variants equal to the query or to the rewrite would only repeat a search.
        alternatives = [
            alternative
            for alternative in clean_items(answer.alternative_queries, MAX_ALTERNATIVE_QUERIES + 2)
            if alternative.lower() not in {query.lower(), rewritten.lower()}
        ][:MAX_ALTERNATIVE_QUERIES]
        analysis = QueryAnalysis(
            rewritten_query=rewritten,
            alternative_queries=alternatives,
            similar_terms=clean_items(answer.similar_terms, MAX_SIMILAR_TERMS),
            categories=list(dict.fromkeys(answer.categories)),
            content_types=list(dict.fromkeys(answer.content_types)),
        )
        with self._lock:
            self._cache[key] = analysis
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return analysis
