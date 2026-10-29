"""Tests for the re-ranking helpers and the fake re-ranker contract."""

import pytest
import torch

from app.reranking.cross_encoder import logits_to_scores
from tests.fakes import FakeReranker


def test_single_logit_goes_through_a_sigmoid() -> None:
    """One output per pair is mapped to [0, 1] with a sigmoid."""
    scores = logits_to_scores(torch.tensor([[0.0], [10.0], [-10.0]]))

    assert scores.tolist() == pytest.approx([0.5, 1.0, 0.0], abs=1e-4)


def test_multi_class_output_uses_the_last_class() -> None:
    """With several labels, the score is the softmax of the last one."""
    scores = logits_to_scores(torch.tensor([[0.0, 0.0], [0.0, 5.0]]))

    assert scores.tolist() == pytest.approx([0.5, 0.9933], abs=1e-3)


def test_fake_reranker_orders_by_overlap() -> None:
    """The passage sharing more query words scores higher, within [0, 1]."""
    reranker = FakeReranker()

    scores = reranker.score("levain forno", ["forno quente", "levain no forno", "listas"])

    assert scores == [0.5, 1.0, 0.0]
    assert reranker.score("como o", ["texto"]) == [0.0]
    assert reranker.score("levain", []) == []
