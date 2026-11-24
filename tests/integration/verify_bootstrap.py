# AI-generated code (Codex): verify checkpointed bootstrap against a fresh MySQL schema.
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

from papersearch import bootstrap
from papersearch.database import connect
from papersearch.encoder import DIM
from papersearch.records import parse_record
from papersearch.snapshot import active_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def main():
    engine = connect()
    source = (FIXTURES / "papers.jsonl").read_bytes().splitlines()
    rows = [
        {
            "row_id": number,
            "paper_id": revision.paper_id,
            "source_version": revision.version_rank,
            "source_updated_at": revision.source_updated_at,
            **asdict(revision.payload),
        }
        for number, revision in enumerate(
            (parse_record(raw, "fixture") for raw in source[:2]), start=1
        )
    ]
    vectors = [
        pack("<384f", *([0.0] * axis + [1.0] + [0.0] * (DIM - axis - 1)))
        for axis in (0, 1)
    ]
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        manifest = dict(
            snapshot_id="1" * 32,
            format_version=2,
            recipe=bootstrap.PUBLISHED_RECIPE,
            coverage=dict(metadata=2, lexical=2, semantic=2),
        )
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pq.write_table(
            pa.Table.from_pylist(rows), folder / "corpus.parquet", row_group_size=1
        )
        pq.write_table(
            pa.table(
                {
                    "vector_row": [0, 1],
                    "row_id": [1, 2],
                    "paper_id": [row["paper_id"] for row in rows],
                    "tokens": [9, 10],
                    "value": pa.array(vectors, type=pa.binary(DIM * 4)),
                }
            ),
            folder / "semantic.parquet",
            row_group_size=1,
        )
        with closing(sqlite3.connect(folder / "lexical.sqlite")) as index, index:
            index.execute(
                "CREATE VIRTUAL TABLE documents USING fts5(title,abstract,paper_id UNINDEXED)"
            )
            index.executemany(
                "INSERT INTO documents(rowid,title,abstract,paper_id) VALUES(:row_id,:title,:abstract,:paper_id)",
                rows,
            )

        import_vectors = bootstrap.import_vectors

        def interrupt(conn, rows):
            if rows[0]["vector_row"] == 1:
                raise RuntimeError("stop before second vector")
            import_vectors(conn, rows)

        with (
            patch.object(bootstrap, "BATCH_SIZE", 1),
            patch.object(bootstrap, "import_vectors", side_effect=interrupt),
        ):
            try:
                bootstrap.bootstrap(engine, folder)
            except RuntimeError as error:
                assert str(error) == "stop before second vector"
            else:
                raise AssertionError("Expected to interrupt bootstrap")
        with engine.connect() as conn:
            assert tuple(conn.execute(text(bootstrap.PROGRESS)).one())[1:] == (2, 1, 0)
            assert active_snapshot(conn, folder)[2] is None

        bootstrap.bootstrap(engine, folder)
        bootstrap.bootstrap(engine, folder)
        with (
            engine.connect() as conn,
            patch.dict("os.environ", {"PAPERSEARCH_BASELINE_DIR": str(folder)}),
        ):
            generation, active_folder, active = active_snapshot(conn, folder)
            assert generation == 1 and active_folder == folder
            assert active["snapshot_id"] == manifest["snapshot_id"]
            expected = conn.execute(
                text("""
                SELECT p.paper_id,e.vector FROM papers p
                JOIN revisions r ON r.revision_id=p.current_revision_id
                JOIN embeddings e ON e.text_id=r.text_id
                ORDER BY r.revision_id
            """)
            ).all()
            assert [(paper, bytes(vector)) for paper, vector in expected] == list(
                zip((row["paper_id"] for row in rows), vectors, strict=True)
            )
            assert (
                conn.scalar(
                    text("SELECT COUNT(*) FROM embeddings WHERE vector IS NULL")
                )
                == 0
            )
    print("Bootstrap checkpoint, atomic activation, vector reuse, and replay passed")


if __name__ == "__main__":
    main()
