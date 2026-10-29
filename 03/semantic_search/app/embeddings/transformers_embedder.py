"""Embeddings computed directly with `transformers` (AutoTokenizer + AutoModel).

Steps for every batch of texts:
1. Prepend the model prefix (`query: ` / `passage: ` for the E5 family).
2. Tokenize with padding (same length inside the batch) and truncation (model window).
3. Forward pass: the model returns one contextual vector per token.
4. Mean pooling over the real tokens (padding excluded via the attention mask).
5. L2 normalization, so the inner product of two vectors is their cosine similarity.
"""

import logging
import time
from collections.abc import Sequence
from typing import Literal

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from app.core.device import configure_torch_threads, resolve_device
from app.embeddings.base import Matrix, ProgressCallback, Vector

logger = logging.getLogger(__name__)


def default_prefixes(model_name: str) -> tuple[str, str]:
    """Return the (query, passage) prefixes a model family was trained with.

    The E5 models are trained for asymmetric search: queries start with `query: `
    and indexed texts with `passage: `. Omitting the prefixes measurably lowers
    their retrieval quality. Other sentence-transformers models use no prefix.

    Args:
        model_name: Hugging Face model id.

    Returns:
        The query prefix and the passage prefix.
    """
    if "e5" in model_name.lower():
        return "query: ", "passage: "
    return "", ""


def mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Average the token vectors of each text, ignoring padding.

    Why not just the `[CLS]` token: sentence-embedding models such as E5 and the
    sentence-transformers family are trained with mean pooling, so the average of
    all token vectors is the representation their training optimized. The `[CLS]`
    vector of these models was not trained to summarize the sentence alone.

    Why the mask: padding tokens only exist to give every text in a batch the same
    length. Averaging them in would change a text's vector depending on which other
    texts happened to share its batch.

    Args:
        token_embeddings: `(batch, tokens, hidden)` output of the model.
        attention_mask: `(batch, tokens)` mask with 1 for real tokens and 0 for padding.

    Returns:
        A `(batch, hidden)` tensor with one pooled vector per text.
    """
    mask = attention_mask.unsqueeze(-1).to(token_embeddings.dtype)
    summed = (token_embeddings * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def l2_normalize(vectors: torch.Tensor) -> torch.Tensor:
    """Scale every vector to unit length.

    With unit vectors, the inner product equals the cosine similarity, which is what
    lets the FAISS inner-product index rank by cosine.

    Args:
        vectors: `(batch, hidden)` tensor.

    Returns:
        The normalized tensor.
    """
    return torch.nn.functional.normalize(vectors, p=2, dim=1)


class TransformersEmbedder:
    """Sentence embeddings with a Hugging Face encoder, mean pooling and L2 norm.

    Args:
        model_name: Hugging Face model id.
        revision: Pinned commit of the model (None uses the latest).
        max_tokens: Token window used when encoding.
        batch_size: Texts per forward pass.
        device: "auto", "cpu" or "cuda".
        num_threads: CPU threads for PyTorch (None keeps the default).
        query_prefix: Overrides the query prefix of the model family.
        passage_prefix: Overrides the passage prefix of the model family.

    Raises:
        ValueError: If `max_tokens` exceeds what the model supports.
    """

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        max_tokens: int = 512,
        batch_size: int = 32,
        device: Literal["auto", "cpu", "cuda"] = "auto",
        num_threads: int | None = None,
        query_prefix: str | None = None,
        passage_prefix: str | None = None,
    ) -> None:
        started = time.perf_counter()
        configure_torch_threads(num_threads)
        self.model_name = model_name
        self.model_revision = revision
        self._device = resolve_device(device)
        self._batch_size = batch_size

        default_query, default_passage = default_prefixes(model_name)
        self._query_prefix = default_query if query_prefix is None else query_prefix
        self._passage_prefix = default_passage if passage_prefix is None else passage_prefix

        self._tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self._model = AutoModel.from_pretrained(model_name, revision=revision)
        # eval() disables dropout, so the same text always gets the same vector.
        self._model.eval()
        self._model.to(self._device)

        model_limit = int(self._model.config.max_position_embeddings)
        tokenizer_limit = int(self._tokenizer.model_max_length)
        supported = min(model_limit, tokenizer_limit)
        if max_tokens > supported:
            raise ValueError(
                f"embedding_max_tokens={max_tokens} exceeds the {supported} tokens "
                f"supported by {model_name}."
            )
        self.max_tokens = max_tokens
        self.dimension = int(self._model.config.hidden_size)

        logger.info(
            "Loaded embedding model %s (dim=%d, device=%s) in %.2fs",
            model_name,
            self.dimension,
            self._device,
            time.perf_counter() - started,
        )

    def embed_documents(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed passages for indexing, in batches.

        Args:
            texts: Passages to embed.
            progress: Optional callback receiving how many texts each batch encoded.

        Returns:
            A `(len(texts), dimension)` float32 matrix of unit vectors.
        """
        return self._embed([f"{self._passage_prefix}{text}" for text in texts], progress)

    def embed_queries(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed query-like texts in batches, with the query prefix.

        Used for the questions generated for each chunk: a user query is then compared
        with questions, both encoded the same way (E5 uses `query: ` on both sides of
        symmetric comparisons).

        Args:
            texts: Questions to embed.
            progress: Optional callback receiving how many texts each batch encoded.

        Returns:
            A `(len(texts), dimension)` float32 matrix of unit vectors.
        """
        return self._embed([f"{self._query_prefix}{text}" for text in texts], progress)

    def embed_query(self, text: str) -> Vector:
        """Embed a search query.

        Args:
            text: The query.

        Returns:
            A `(dimension,)` float32 unit vector.
        """
        vector: Vector = self._embed([f"{self._query_prefix}{text}"])[0]
        return vector

    def count_tokens(self, text: str) -> int:
        """Count the tokens of a text with the model's tokenizer.

        Args:
            text: Any text.

        Returns:
            The number of tokens, special tokens excluded.
        """
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])

    def _embed(self, texts: list[str], progress: ProgressCallback | None = None) -> Matrix:
        """Encode texts in batches and restore the original order.

        Texts are sorted by length before batching: each batch is padded to its
        longest text, so grouping texts of similar length wastes less computation
        on padding tokens.

        Args:
            texts: Texts, prefixes already applied.
            progress: Optional per-batch progress callback.

        Returns:
            A `(len(texts), dimension)` float32 matrix of unit vectors.
        """
        output = np.zeros((len(texts), self.dimension), dtype=np.float32)
        order = sorted(range(len(texts)), key=lambda index: len(texts[index]), reverse=True)

        for start in range(0, len(order), self._batch_size):
            batch_indices = order[start : start + self._batch_size]
            batch = [texts[index] for index in batch_indices]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_tokens,
                return_tensors="pt",
            ).to(self._device)

            # inference_mode skips autograd bookkeeping: less memory, faster.
            with torch.inference_mode():
                token_embeddings = self._model(**encoded).last_hidden_state
                pooled = mean_pooling(token_embeddings, encoded["attention_mask"])
                vectors = l2_normalize(pooled)

            output[batch_indices] = vectors.cpu().numpy().astype(np.float32)
            if progress is not None:
                progress(len(batch))
        return output
