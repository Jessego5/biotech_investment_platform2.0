"""
Tests for the reranker's behaviour around the model rather than the model.

Whether the judgement is any good is a question for eval_retrieval.py. What can
be pinned down here is that a reranker which cannot reach the model, or gets
nonsense back from it, leaves the search exactly as good as it was — the whole
stage is an optimisation, and an optimisation that can break retrieval is a
liability.
"""

import json

import pytest

from app import rerank as R


def _hits(n):
    return [{"chunk_id": i, "text": f"passage {i}", "ticker": "AAA",
             "fiscal_year": 2025, "section": "risk_factors", "score": 0.5}
            for i in range(1, n + 1)]


class _Reply:
    def __init__(self, payload):
        self.choices = [type("C", (), {"message": type("M", (), {
            "content": json.dumps(payload)})()})()]


def _stub(monkeypatch, payload=None, boom=False):
    class Completions:
        def create(self, **kwargs):
            if boom:
                raise RuntimeError("the API is down")
            return _Reply(payload)
    class Client:
        chat = type("Chat", (), {"completions": Completions()})()
    monkeypatch.setattr(R, "_client", lambda: Client())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_no_api_key_leaves_the_order_alone(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    hits = _hits(5)
    assert R.rerank("q", hits, keep=3) == hits[:3]


def test_a_failed_call_leaves_the_order_alone(monkeypatch):
    _stub(monkeypatch, boom=True)
    hits = _hits(5)
    assert R.rerank("q", hits, keep=3) == hits[:3]


def test_nonsense_from_the_model_leaves_the_order_alone(monkeypatch):
    _stub(monkeypatch, payload={"scores": [{"nope": 1}]})
    hits = _hits(4)
    assert [h["chunk_id"] for h in R.rerank("q", hits, keep=2)] == [1, 2]


def test_scores_reorder_the_candidates(monkeypatch):
    _stub(monkeypatch, payload={"scores": [
        {"i": 1, "score": 1}, {"i": 2, "score": 9}, {"i": 3, "score": 5}]})
    out = R.rerank("q", _hits(3), keep=3)
    assert [h["chunk_id"] for h in out] == [2, 3, 1]
    assert out[0]["rerank"] == 9


def test_out_of_range_indices_are_ignored(monkeypatch):
    # the model naming a passage that was never sent must not drop a real one
    _stub(monkeypatch, payload={"scores": [{"i": 99, "score": 10}, {"i": 2, "score": 8}]})
    out = R.rerank("q", _hits(3), keep=3)
    assert [h["chunk_id"] for h in out] == [2, 1, 3]


def test_unjudged_passages_keep_their_retrieved_position(monkeypatch):
    """Silence about a passage is not evidence against it: it should fall in
    behind the judged ones in the order retrieval gave, not be discarded."""
    _stub(monkeypatch, payload={"scores": [{"i": 3, "score": 7}]})
    out = R.rerank("q", _hits(4), keep=4)
    assert [h["chunk_id"] for h in out] == [3, 1, 2, 4]


def test_a_single_candidate_is_not_worth_a_call(monkeypatch):
    _stub(monkeypatch, payload={"scores": [{"i": 1, "score": 0}]})
    hits = _hits(1)
    assert R.rerank("q", hits, keep=6) == hits


def test_the_cosine_score_is_never_overwritten(monkeypatch):
    """The relevance floor is calibrated on cosine. If reranking replaced that
    score, the honest 'no data' would quietly stop working."""
    _stub(monkeypatch, payload={"scores": [{"i": 2, "score": 10}]})
    out = R.rerank("q", _hits(3), keep=3)
    assert all(h["score"] == 0.5 for h in out)
