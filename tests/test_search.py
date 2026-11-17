# AI-generated code (Codex): snapshot search ranking and row identity.
import sqlite3
from contextlib import closing

from papersearch.lexical import search_lexical


def test_bm25_alias_field_and_revision(tmp_path):
    path = tmp_path / "search.sqlite"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE VIRTUAL TABLE documents USING fts5(title, abstract, paper_id UNINDEXED, revision_id UNINDEXED)"
        )
        conn.executemany(
            "INSERT INTO documents VALUES(?,?,?,?)",
            [
                (
                    "Vision-language models for diagrams",
                    "The method retrieves diagrams.",
                    "a",
                    10,
                ),
                ("A review", "Vision language models retrieve diagrams.", "b", 20),
                ("Another review", "Unrelated abstract.", "c", 30),
            ],
        )
    hits, more = search_lexical(path, "VLM", "title", 0, 1)
    assert not more
    assert [(row["paper_id"], row["revision_id"]) for row in hits] == [("a", 10)]
    hits, more = search_lexical(path, "vision language models diagrams", "all", 0, 1)
    assert more and hits[0]["paper_id"] == "a"
