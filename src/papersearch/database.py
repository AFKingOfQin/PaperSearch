import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from .embeddings import enqueue
from .encoder import eligible
from .records import canonical, revision_values


def connect():
    url = URL.create(
        "mysql+mysqlconnector",
        username=os.environ.get("MYSQL_USER", "papersearch"),
        password=os.environ["MYSQL_PASSWORD"],
        host=os.environ.get("MYSQL_HOST", "mysql"),
        database=os.environ.get("MYSQL_DATABASE", "papersearch"),
    )
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def intern_text(conn, title, abstract):
    data = canonical([title, abstract]).encode()
    args = {"prefix": data[:64].hex(), "body": data.hex()}
    # Upsert locks the prefix until the caller commits. Full binary equality decides reuse.
    conn.execute(
        text("""
        INSERT INTO text_prefixes VALUES(UNHEX(:prefix))
        ON DUPLICATE KEY UPDATE prefix=prefix
    """),
        args,
    )
    found = conn.scalar(
        text("""
        SELECT text_id FROM paper_texts
        WHERE prefix=UNHEX(:prefix) AND content=UNHEX(:body) FOR UPDATE
    """),
        args,
    )
    if found is not None:
        return found
    return conn.execute(
        text("""
        INSERT INTO paper_texts(prefix,content) VALUES(UNHEX(:prefix),UNHEX(:body))
    """),
        args,
    ).lastrowid


def apply_revision(conn, revision):
    source, complete = conn.execute(
        text("SELECT source_id,complete FROM baseline_import WHERE id=1 FOR SHARE")
    ).one()
    if source is not None and not complete:
        raise RuntimeError("Finish the published snapshot import before consuming updates")
    args = revision_values(revision)
    conn.execute(
        text("""
        INSERT INTO papers(paper_id) VALUES(:paper)
        ON DUPLICATE KEY UPDATE paper_id=paper_id
    """),
        args,
    )
    existing = conn.scalar(
        text("""
        SELECT revision_id FROM revisions
        WHERE paper_id=:paper AND version_rank=:rank AND source_updated_at=:stamp
          AND payload=UNHEX(:payload)
    """),
        args,
    )
    if existing is not None:
        return existing, "duplicate"
    text_id = intern_text(conn, revision.payload.title, revision.payload.abstract)
    revision_id = conn.execute(
        text("""
        INSERT INTO revisions(paper_id,version_rank,source_updated_at,payload,text_id)
        VALUES(:paper,:rank,:stamp,UNHEX(:payload),:text_id)
    """),
        {**args, "text_id": text_id},
    ).lastrowid
    winner = conn.scalar(
        text("""
        SELECT MIN(revision_id) FROM revisions WHERE paper_id=:paper
        GROUP BY version_rank,source_updated_at HAVING COUNT(*)=1
        ORDER BY version_rank DESC,source_updated_at DESC LIMIT 1
    """),
        args,
    )
    changed = conn.execute(
        text("""
        UPDATE papers SET current_revision_id=:winner
        WHERE paper_id=:paper AND NOT (current_revision_id <=> :winner)
    """),
        {**args, "winner": winner},
    ).rowcount
    if changed:
        conn.execute(
            text("UPDATE pipeline_state SET generation=generation+1 WHERE id=1")
        )
    if winner == revision_id:
        if eligible(
            revision.paper_id,
            {
                "published": revision.payload.published,
                "categories": revision.payload.categories,
            },
        ):
            enqueue(conn, text_id)
        return revision_id, "applied"
    variants = conn.scalar(
        text("""
        SELECT COUNT(*) FROM revisions
        WHERE paper_id=:paper AND version_rank=:rank AND source_updated_at=:stamp
    """),
        args,
    )
    return revision_id, "conflict" if variants > 1 else "stale"
