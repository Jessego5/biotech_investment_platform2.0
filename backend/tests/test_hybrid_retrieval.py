"""
Tests for the parts of hybrid retrieval that do not need a database.

The ranking itself needs Postgres, a GIN index and 334,624 embedded passages, so
it is measured by eval_retrieval.py rather than asserted here. What IS asserted
here is the arithmetic underneath it, because a fusion that silently favours one
ranking is the kind of defect that shows up as "retrieval got slightly worse"
and never as an error.
"""

import json

import pytest

from app.semantic import (RRF_K, DF_CEILING, MAX_LEXICAL_TERMS, _rrf,
                          _SAFE_LEXEME, _fts_stats)
import app.semantic as semantic


# - reciprocal rank fusion

def test_rrf_scores_by_position_not_by_list_length():
    # the same id first in both lists must beat one that is first in only one
    both = _rrf([["a", "b"], ["a", "c"]])
    assert both["a"] > both["b"]
    assert both["a"] > both["c"]


def test_rrf_does_not_penalise_absence():
    # "c" appears in one ranking only; it should still score, not go negative
    points = _rrf([["a"], ["b", "c"]])
    assert points["c"] > 0
    assert set(points) == {"a", "b", "c"}


def test_rrf_uses_the_documented_constant():
    # first place is worth exactly 1/(K+1); if the constant moves, this moves
    assert _rrf([["only"]])["only"] == pytest.approx(1.0 / (RRF_K + 1))


def test_rrf_of_nothing_is_nothing():
    assert _rrf([[], []]) == {}


def test_rrf_top_of_one_list_can_lose_to_agreement():
    """
    The property the whole design rests on: a passage both rankings like beats a
    passage only one of them put first. Without this, fusing is just an
    expensive way to run two searches and keep the louder one.
    """
    dense = ["solo", "agreed"]
    lexical = ["other", "agreed"]
    points = _rrf([dense, lexical])
    assert points["agreed"] > points["solo"]


# - lexeme safety

@pytest.mark.parametrize("lexeme", ["bionano", "genom", "after-tax", "nct04368728", "10"])
def test_safe_lexemes_are_accepted(lexeme):
    assert _SAFE_LEXEME.match(lexeme)


@pytest.mark.parametrize("lexeme", ["", "'; drop table", "a b", "-lead", "Bionano", "it's"])
def test_unsafe_lexemes_are_rejected(lexeme):
    """
    These are interpolated into a tsquery string rather than bound, so the
    filter is the only thing between a lexeme and the parser.
    """
    assert not _SAFE_LEXEME.match(lexeme)


# - corpus statistics

def test_stats_file_is_present_and_shaped():
    stats = _fts_stats()
    assert stats["sample_docs"] > 0
    assert len(stats["df"]) > 100
    # the commonest words in annual reports must be over the ceiling, or the
    # lexical search goes back to matching most of the corpus
    docs = stats["sample_docs"]
    assert stats["df"]["may"] / docs > DF_CEILING


def test_missing_stats_degrade_rather_than_crash(monkeypatch, tmp_path):
    """
    Without the file every word looks rare, which makes the AND stricter and the
    search worse. It must not make it fail: the file is generated, and generated
    files go missing.
    """
    monkeypatch.setattr(semantic, "_FTS_STATS", None)
    monkeypatch.setattr(semantic.os.path, "dirname", lambda _p: str(tmp_path))
    stats = _fts_stats()
    assert stats == {"sample_docs": 0, "df": {}}
    monkeypatch.setattr(semantic, "_FTS_STATS", None)


def test_term_budget_is_small():
    # the AND gets harder to satisfy with every term; this is the relaxation
    # loop's starting point and is deliberately low
    assert 1 <= MAX_LEXICAL_TERMS <= 6
