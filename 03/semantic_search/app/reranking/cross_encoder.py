"""Cross-encoder re-ranker built directly with `transformers`.

Bi-encoder vs. cross-encoder:
- The bi-encoder (the embedding model) encodes the query and each passage
  *separately*. Passages can be embedded once at indexing time, and the search is a
  cheap vector comparison, but the two texts never "see" each other.
- The cross-encoder reads the query and the passage *together* in one forward pass,
  so every query token attends to every passage token. It judges relevance much more
  precisely, but needs one forward pass per (query, passage) pair, at search time.

That cost is why it only re-orders the few dozen best candidates of the first stage
instead of scanning the whole corpus: retrieval gives recall, re-ranking gives
precision. The model used by default was trained on mMARCO (MS MARCO translated to
many languages, Portuguese included), so it handles Portuguese passages and English
queries.
"""

import logging
import time
from collections.abc import Sequence
from typing import Literal

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.core.device import configure_torch_threads, resolve_device

logger = logging.getLogger(__name__)


def logits_to_scores(logits: torch.Tensor) -> torch.Tensor:
    """Turn the classifier output into relevance scores in [0, 1].

    Models with a single output return a relevance logit, mapped to [0, 1] with a
    sigmoid. Models with several classes are read as "probability of the last class
    (relevant)" through a softmax.

    Args:
        logits: `(batch, num_labels)` output of the classification head.

    Returns:
        A `(batch,)` tensor of scores.
    """
    if logits.shape[-1] == 1:
        return torch.sigmoid(logits[:, 0])
    return torch.softmax(logits, dim=-1)[:, -1]


class CrossEncoderReranker:
    """Scores (query, passage) pairs with a sequence-classification model.

    Args:
        model_name: Hugging Face model id.
        revision: Pinned commit of the model (None uses the latest).
        max_tokens: Token window for each pair.
        batch_size: Pairs per forward pass.
        device: "auto", "cpu" or "cuda".
        num_threads: CPU threads for PyTorch (None keeps the default).
    """

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        max_tokens: int = 512,
        batch_size: int = 16,
        device: Literal["auto", "cpu", "cuda"] = "auto",
        num_threads: int | None = None,
    ) -> None:
        started = time.perf_counter()
        configure_torch_threads(num_threads)
        self.model_name = model_name
        self.model_revision = revision
        self._device = resolve_device(device)
        self._batch_size = batch_size
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            model_name, revision=revision
        )
        self._model.eval()
        self._model.to(self._device)
        self._max_tokens = min(max_tokens, int(self._tokenizer.model_max_length))
        logger.info(
            "Loaded cross-encoder %s (device=%s) in %.2fs",
            model_name,
            self._device,
            time.perf_counter() - started,
        )

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Score each passage against the query.

        Args:
            query: The search query.
            passages: Candidate passages.

        Returns:
            One relevance score in [0, 1] per passage, in the same order.
        """
        scores: list[float] = []
        for start in range(0, len(passages), self._batch_size):
            batch = list(passages[start : start + self._batch_size])
            # The pair is encoded as "[CLS] query [SEP] passage [SEP]". When it is too
            # long, only the passage is truncated: the query must stay complete.
            encoded = self._tokenizer(
                [query] * len(batch),
                batch,
                padding=True,
                truncation="only_second",
                max_length=self._max_tokens,
                return_tensors="pt",
            ).to(self._device)
            with torch.inference_mode():
                logits = self._model(**encoded).logits
            scores.extend(logits_to_scores(logits).cpu().tolist())
        return scores
