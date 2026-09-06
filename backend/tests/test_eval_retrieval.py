"""
This tests the retrieval eval's scoring. A measurement instrument that is wrong
in the flattering direction is worse than no instrument, because it gets quoted,
so these check the three ways this one could flatter: counting a near miss as a
hit, counting a miss as a hit, and averaging in a way that hides misses.
"""

import eval_retrieval as E


CASE = {"chunk_id": 100, "filing_id": 7, "ordinal": 5, "section": "risk_factors"}


def _hit(chunk_id, filing_id=7, ordinal=5, section="risk_factors", score=0.5):
    return {"chunk_id": chunk_id, "filing_id": filing_id, "ordinal": ordinal,
            "section": section, "score": score}


# - where the target landed

def test_exact_hit_is_found_at_its_rank():
    hits = [_hit(1, filing_id=2), _hit(100)]
    exact, _adjacent, _document = E._rank_of(hits, CASE)
    assert exact == 2


def test_a_different_filing_is_not_credited():
    """The failure that would make every number look good: another company's
    passage about the same subject counting as a find."""
    hits = [_hit(1, filing_id=999, ordinal=5)]
    exact, adjacent, document = E._rank_of(hits, CASE)
    assert (exact, adjacent, document) == (None, None, None)


def test_the_chunk_next_door_is_adjacent_but_not_exact():
    # chunks overlap by 300 characters, so this is a near miss and is reported
    # as one, never as a hit
    hits = [_hit(101, ordinal=6)]
    exact, adjacent, document = E._rank_of(hits, CASE)
    assert exact is None
    assert adjacent == 1
    assert document == 1


def test_far_chunk_of_the_right_filing_is_document_only():
    hits = [_hit(140, ordinal=40)]
    exact, adjacent, document = E._rank_of(hits, CASE)
    assert (exact, adjacent) == (None, None)
    assert document == 1


def test_adjacent_requires_the_same_section():
    # ordinal is only meaningful within a section, so a chunk 1 away in another
    # section of the same filing is not the passage next door
    hits = [_hit(101, ordinal=6, section="mdna")]
    _exact, adjacent, document = E._rank_of(hits, CASE)
    assert adjacent is None
    assert document == 1


# - the averages

def test_recall_at_k_counts_only_ranks_within_k():
    ranks = [1, 5, 11, None]
    assert E._at(ranks, 1) == 0.25
    assert E._at(ranks, 5) == 0.5
    assert E._at(ranks, 10) == 0.5


def test_misses_are_averaged_in_not_dropped():
    """
    The flattering bug: computing MRR over found items only. Half misses have to
    halve the score, not leave it at 1.0.
    """
    assert E._mrr([1, None]) == 0.5
    assert E._mrr([1, 1]) == 1.0


def test_empty_is_zero_not_an_error():
    assert E._at([], 10) == 0.0
    assert E._mrr([]) == 0.0
