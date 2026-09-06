"""
This holds the vector index and the vector search to the same distance operator.
Nothing fails when they stop agreeing: the index builds, the query runs, the
planner quietly declines to use an index built for an operator the query does not
ask for, and the only evidence is that the search is as slow as it was before,
with a two-gigabyte index on disk implying otherwise. So the operator class in
the migration is checked against the operator the query actually emits.
"""

from sqlalchemy.dialects import postgresql

import migrate_vector_index as migration
from app.models import FilingChunk, Trial


def _compiled(column):
    """The SQL the search really sends, not a description of it."""
    return str(column.cosine_distance([0.0] * 1536).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_the_search_orders_by_the_operator_the_index_is_built_for():
    assert migration.OPERATOR in _compiled(FilingChunk.embedding)
    assert migration.OPERATOR in _compiled(Trial.embedding)


def test_the_operator_class_matches_the_operator():
    # <=> is cosine, <-> is L2, <#> is inner product. Changing the query to one
    # of the others means rebuilding every index here for it.
    assert {"<=>": "vector_cosine_ops",
            "<->": "vector_l2_ops",
            "<#>": "vector_ip_ops"}[migration.OPERATOR] == migration.OPS_CLASS


def test_every_indexed_column_is_one_the_search_reads():
    # an index over a column nothing queries is 2 GB of disk and a build every
    # deploy, for nothing
    searched = {("filing_chunks", "embedding"), ("filing_chunks", "embedding_ctx"),
                ("trials", "embedding")}
    for _, table, column in migration.INDEXES + [migration.CONTEXT_INDEX]:
        assert (table, column) in searched


def test_the_contextual_space_is_not_built_by_default():
    # it is the experiment, and it costs the same again in build time and disk
    assert migration.CONTEXT_INDEX not in migration.INDEXES
