import json

import pyarrow.parquet as pq
from sqlalchemy import bindparam, text

from .encoder import DIM, MODEL, RECIPE, REVISION
from .records import canonical

PAYLOAD_FIELDS = (
    "title",
    "abstract",
    "authors",
    "categories",
    "published",
    "source_url",
    "doi",
)
PUBLISHED_RECIPE = dict(
    kind="bge-onnx-cpu-v1",
    model_id=MODEL,
    model_revision=REVISION,
    preprocessing="title-lf-abstract-cls128-v1",
)
PROGRESS = (
    "SELECT source_id,corpus_row,vector_row,complete FROM baseline_import WHERE id=1"
)
BATCH_SIZE = 1024


def published_manifest(folder):
    with (folder / "manifest.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest["format_version"] != 2 or manifest["recipe"] != PUBLISHED_RECIPE:
        raise ValueError("Expected a version 2 publication with the pinned BGE recipe")
    manifest["recipe"] = RECIPE
    manifest["generation"] = 1
    return manifest


def batches(file, columns, completed, position):
    # Skip whole row groups, then let Arrow combine small groups into bounded batches.
    skipped = 0
    for group in range(file.num_row_groups):
        rows = file.metadata.row_group(group).num_rows
        if skipped + rows > completed:
            break
        skipped += rows
    else:
        return

    for batch in file.iter_batches(
        BATCH_SIZE, row_groups=range(group, file.num_row_groups), columns=columns
    ):
        start = max(completed - skipped, 0)
        if start < len(batch):
            page = batch.slice(start).to_pylist()
            for number, row in enumerate(page, skipped + start + position):
                if row[columns[0]] != number:
                    raise ValueError("Published row IDs are out of order")
            yield page
        skipped += len(batch)


def text_ids_for_prefixes(conn, prefixes):
    parameters = {f"p{i}": prefix.hex() for i, prefix in enumerate(prefixes)}
    values = ",".join(f"UNHEX(:{name})" for name in parameters)
    statement = text(
        f"SELECT text_id,content FROM paper_texts WHERE prefix IN ({values}) FOR UPDATE"
    )
    return {
        bytes(row.content): row.text_id for row in conn.execute(statement, parameters)
    }


def intern_text_batch(conn, texts):
    by_content = {value: value[:64] for value in texts}
    prefixes = sorted(set(by_content.values()))
    conn.execute(
        text("INSERT IGNORE INTO text_prefixes(prefix) VALUES(UNHEX(:prefix))"),
        [{"prefix": prefix.hex()} for prefix in prefixes],
    )
    ids = text_ids_for_prefixes(conn, prefixes)
    missing = {
        content: prefix for content, prefix in by_content.items() if content not in ids
    }
    if missing:
        conn.execute(
            text(
                "INSERT INTO paper_texts(prefix,content) VALUES(UNHEX(:prefix),UNHEX(:content))"
            ),
            [
                {"prefix": prefix.hex(), "content": content.hex()}
                for content, prefix in missing.items()
            ],
        )
        ids.update(text_ids_for_prefixes(conn, sorted(set(missing.values()))))
    return ids


def import_corpus(conn, rows):
    contents = [canonical([row["title"], row["abstract"]]).encode() for row in rows]
    text_ids = intern_text_batch(conn, contents)
    conn.execute(
        text("INSERT INTO papers(paper_id) VALUES(:paper)"),
        [{"paper": row["paper_id"]} for row in rows],
    )
    conn.execute(
        text("""
            INSERT INTO revisions(revision_id,paper_id,version_rank,source_updated_at,payload,text_id)
            VALUES(:revision,:paper,:rank,:stamp,UNHEX(:payload),:text_id)
        """),
        [
            dict(
                revision=row["row_id"],
                paper=row["paper_id"],
                rank=row["source_version"] or 0,
                stamp=row["source_updated_at"],
                payload=canonical({key: row[key] for key in PAYLOAD_FIELDS})
                .encode()
                .hex(),
                text_id=text_ids[content],
            )
            for row, content in zip(rows, contents, strict=True)
        ],
    )
    conn.execute(
        text("""
            UPDATE revisions r STRAIGHT_JOIN papers p USING(paper_id)
            SET p.current_revision_id=r.revision_id
            WHERE r.revision_id BETWEEN :first AND :last
        """),
        {"first": rows[0]["row_id"], "last": rows[-1]["row_id"]},
    )


def import_vectors(conn, rows):
    statement = text(
        "SELECT revision_id,paper_id,text_id FROM revisions WHERE revision_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    revisions = {
        row.revision_id: row
        for row in conn.execute(statement, {"ids": [row["row_id"] for row in rows]})
    }
    for row in rows:
        if revisions[row["row_id"]].paper_id != row["paper_id"]:
            raise ValueError("A published vector points to a different paper")
    conn.execute(
        text("""
            INSERT INTO embeddings(text_id,recipe,vector,tokens)
            VALUES(:id,:recipe,UNHEX(:vector),:tokens)
            ON DUPLICATE KEY UPDATE text_id=text_id
        """),
        [
            dict(
                id=revisions[row["row_id"]].text_id,
                recipe=RECIPE,
                vector=row["value"].hex(),
                tokens=row["tokens"],
            )
            for row in rows
        ],
    )


def bootstrap(engine, folder):
    manifest = published_manifest(folder)
    source_id = manifest["snapshot_id"]
    coverage = manifest["coverage"]
    corpus_columns = (
        "row_id",
        "paper_id",
        "source_version",
        "source_updated_at",
        *PAYLOAD_FIELDS,
    )
    vector_columns = ("vector_row", "row_id", "paper_id", "tokens", "value")
    with (
        pq.ParquetFile(folder / "corpus.parquet") as corpus,
        pq.ParquetFile(folder / "semantic.parquet") as vectors,
    ):
        if (
            corpus.metadata.num_rows != coverage["metadata"]
            or vectors.metadata.num_rows != coverage["semantic"]
            or vectors.schema_arrow.field("value").type.byte_width != DIM * 4
            or not (folder / "lexical.sqlite").is_file()
        ):
            raise ValueError("Published files do not match the manifest")
        with engine.begin() as conn:
            state = conn.execute(text(PROGRESS + " FOR UPDATE")).one()
            if state.source_id not in (None, source_id):
                raise ValueError("This database is bound to another published snapshot")
            if state.complete:
                return manifest
            if state.source_id is None:
                used = conn.scalar(text("SELECT EXISTS(SELECT 1 FROM papers)"))
                active = conn.scalar(
                    text("SELECT active_snapshot FROM pipeline_state WHERE id=1")
                )
                if used or active:
                    raise ValueError("Bootstrap needs a fresh database")
                conn.execute(
                    text("UPDATE baseline_import SET source_id=:source WHERE id=1"),
                    {"source": source_id},
                )

        for file, columns, cursor, position, importer in (
            (corpus, corpus_columns, "corpus_row", 1, import_corpus),
            (vectors, vector_columns, "vector_row", 0, import_vectors),
        ):
            completed = getattr(state, cursor)
            for rows in batches(file, columns, completed, position):
                last = rows[-1][columns[0]] + 1 - position
                with engine.begin() as conn:
                    progress = conn.execute(text(PROGRESS + " FOR UPDATE")).one()
                    current = getattr(progress, cursor)
                    if current >= last:
                        completed = last
                        continue
                    if current != completed:
                        raise ValueError(
                            "Bootstrap progress changed. Resume the command."
                        )
                    importer(conn, rows)
                    conn.execute(
                        text(f"UPDATE baseline_import SET {cursor}=:last WHERE id=1"),
                        {"last": last},
                    )
                completed = last

    with engine.begin() as conn:
        progress = conn.execute(text(PROGRESS + " FOR UPDATE")).one()
        if progress.complete:
            return manifest
        if (
            progress.corpus_row != coverage["metadata"]
            or progress.vector_row != coverage["semantic"]
        ):
            raise ValueError("Published snapshot import is incomplete")
        conn.execute(text("UPDATE baseline_import SET complete=TRUE WHERE id=1"))
        conn.execute(
            text(
                "UPDATE pipeline_state SET generation=1,active_snapshot=:id WHERE id=1"
            ),
            {"id": source_id},
        )
    return manifest
