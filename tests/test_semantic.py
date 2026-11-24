# AI-generated code (Codex): deterministic semantic scope and input recipe.
import pyarrow as pa
import pyarrow.parquet as pq

from papersearch.bootstrap import batches
from papersearch.encoder import eligible, passage


def test_fixture_and_recent_cross_listed_papers_are_eligible():
    assert eligible("fixture:river", {"published": None, "categories": []})
    assert eligible(
        "arxiv:2401.00001",
        {"published": "2024-01-01", "categories": ["math.OC", "cs.LG"]},
    )
    assert not eligible(
        "arxiv:2401.00001", {"published": None, "categories": ["cs.LG"]}
    )


def test_passage_keeps_title_and_abstract_separate():
    assert (
        passage("River models", "A study of streams.")
        == "River models\nA study of streams."
    )
    assert passage("River models", "") == "River models"


def test_published_batches_resume_inside_a_row_group(tmp_path):
    path = tmp_path / "positions.parquet"
    pq.write_table(pa.table({"row_id": [1, 2, 3, 4, 5]}), path, row_group_size=2)
    with pq.ParquetFile(path) as file:
        remaining = list(batches(file, ("row_id",), completed=3, position=1))
    assert remaining == [[{"row_id": 4}, {"row_id": 5}]]
