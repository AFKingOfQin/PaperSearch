from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

HISTORY = pa.schema(
    [
        ("revision_id", pa.int64()),
        ("paper_id", pa.string()),
        ("version_rank", pa.int32()),
        ("source_updated_at", pa.string()),
        ("payload", pa.string()),
    ]
)


def export_history(engine, path, after=0):
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        conn.begin(),
        pq.ParquetWriter(staging, HISTORY) as writer,
    ):
        while (
            page := conn.execute(
                text("""
            SELECT revision_id,paper_id,version_rank,source_updated_at,payload
            FROM revisions WHERE revision_id>:after ORDER BY revision_id LIMIT 128
        """),
                {"after": after},
            )
            .mappings()
            .all()
        ):
            rows = [{**row, "payload": row["payload"].decode("utf-8")} for row in page]
            writer.write_table(pa.Table.from_pylist(rows, schema=HISTORY))
            after = rows[-1]["revision_id"]
    staging.rename(path)
