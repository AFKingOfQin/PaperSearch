import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

from .encoder import DIM, MAX_TOKENS, RECIPE, eligible

STR = pa.string()
CORPUS = pa.schema(
    [
        ("row_id", pa.int64()),
        ("paper_id", STR),
        ("revision_id", pa.int64()),
        ("version_rank", pa.int32()),
        ("source_updated_at", STR),
        ("title", STR),
        ("abstract", STR),
        ("authors", pa.list_(STR)),
        ("categories", pa.list_(STR)),
        ("published", STR),
        ("source_url", STR),
        ("doi", STR),
    ]
)
VECTORS = pa.schema(
    [("row_id", pa.int64()), ("value", pa.binary(DIM * 4)), ("tokens", pa.int32())]
)


def snapshots_root():
    return Path(os.environ.get("ARTIFACT_DIR", "artifacts")) / "snapshots"


def pages(conn):
    after = ""
    while (
        page := conn.execute(
            text("""
        SELECT p.paper_id,r.revision_id,r.version_rank,r.source_updated_at,r.payload,e.vector,e.tokens
        FROM papers p JOIN revisions r ON r.revision_id=p.current_revision_id
        LEFT JOIN embeddings e ON e.text_id=r.text_id AND e.recipe=:recipe
        WHERE p.paper_id>:after ORDER BY p.paper_id LIMIT 128
    """),
            {"after": after, "recipe": RECIPE},
        )
        .mappings()
        .all()
    ):
        yield page
        after = page[-1]["paper_id"]


def active_snapshot(conn, root):
    state = conn.execute(
        text("SELECT generation,active_snapshot FROM pipeline_state WHERE id=1")
    ).one()
    if state.active_snapshot is None:
        return state.generation, None
    path = root / state.active_snapshot / "manifest.json"
    return state.generation, json.loads(path.read_text(encoding="utf-8"))


def publish_snapshot(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    snapshot_id = uuid4().hex
    staging = root / (".building-" + snapshot_id)
    staging.mkdir()
    count = semantic = candidates = shortened = 0
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        conn.begin(),
        pq.ParquetWriter(staging / "corpus.parquet", CORPUS) as writer,
        pq.ParquetWriter(staging / "semantic.parquet", VECTORS) as vector_writer,
        closing(sqlite3.connect(staging / "lexical.sqlite")) as index,
        index,
    ):
        state = conn.execute(
            text("SELECT generation,active_snapshot FROM pipeline_state WHERE id=1")
        ).one()
        index.execute("""
            CREATE VIRTUAL TABLE documents USING fts5(
                title, abstract, paper_id UNINDEXED, revision_id UNINDEXED, tokenize='unicode61'
            )
        """)
        for page in pages(conn):
            rows, vectors = [], []
            for item in page:
                count += 1
                record = dict(item)
                payload = json.loads(record.pop("payload"))
                vector, tokens = record.pop("vector"), record.pop("tokens")
                rows.append(dict(row_id=count, **record, **payload))
                if eligible(record["paper_id"], payload):
                    candidates += 1
                    if vector is not None:
                        vectors.append(
                            dict(row_id=count, value=bytes(vector), tokens=tokens)
                        )
                        semantic += 1
                        shortened += tokens > MAX_TOKENS
            if vectors:
                vector_writer.write_table(pa.Table.from_pylist(vectors, schema=VECTORS))
            writer.write_table(pa.Table.from_pylist(rows, schema=CORPUS))
            index.executemany(
                "INSERT INTO documents(rowid,title,abstract,paper_id,revision_id) VALUES(?,?,?,?,?)",
                [
                    (
                        row["row_id"],
                        row["title"],
                        row["abstract"],
                        row["paper_id"],
                        row["revision_id"],
                    )
                    for row in rows
                ],
            )
    manifest = dict(
        snapshot_id=snapshot_id,
        generation=state.generation,
        recipe=RECIPE,
        coverage=dict(
            metadata=count,
            lexical=count,
            semantic=semantic,
            semantic_eligible=candidates,
            semantic_truncated=shortened,
        ),
    )
    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    staging.rename(root / snapshot_id)
    with engine.begin() as conn:
        updated = conn.execute(
            text("""
            UPDATE pipeline_state SET active_snapshot=:new
            WHERE id=1 AND active_snapshot <=> :old
        """),
            {"new": snapshot_id, "old": state.active_snapshot},
        )
        if updated.rowcount != 1:
            raise ValueError(
                "Another builder published a snapshot. Build again against the new state."
            )
    return manifest
