import json
from uuid import uuid4

from sqlalchemy import text

from .encoder import RECIPE, Encoder, eligible, passage


def enqueue(conn, text_id):
    conn.execute(
        text("""
        INSERT INTO embeddings(text_id,recipe) VALUES(:id,:recipe)
        ON DUPLICATE KEY UPDATE text_id=text_id
    """),
        {"id": text_id, "recipe": RECIPE},
    )


def backfill(engine):
    after = ""
    while True:
        with engine.begin() as conn:
            page = conn.execute(
                text("""
                SELECT p.paper_id,r.payload,r.text_id FROM papers p
                JOIN revisions r ON r.revision_id=p.current_revision_id
                WHERE p.paper_id>:after ORDER BY p.paper_id LIMIT 128
            """),
                {"after": after},
            ).all()
            if not page:
                return
            ids = {
                row.text_id
                for row in page
                if eligible(row.paper_id, json.loads(row.payload))
            }
            for text_id in sorted(ids):
                enqueue(conn, text_id)
        after = page[-1].paper_id


def claim(engine, count, ttl):
    token = str(uuid4())
    with (
        engine.connect().execution_options(isolation_level="READ COMMITTED") as conn,
        conn.begin(),
    ):
        jobs = (
            conn.execute(
                text("""
            SELECT text_id FROM embeddings
            WHERE recipe=:recipe AND vector IS NULL
              AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6))
            ORDER BY text_id LIMIT :count FOR UPDATE SKIP LOCKED
        """),
                {"recipe": RECIPE, "count": count},
            )
            .scalars()
            .all()
        )
        if not jobs:
            return token, []
        rows = [
            {"id": item, "recipe": RECIPE, "ttl": ttl, "token": token} for item in jobs
        ]
        conn.execute(
            text("""
            UPDATE embeddings SET lease_token=:token, lease_until=TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6))
            WHERE text_id=:id AND recipe=:recipe
        """),
            rows,
        )
        work = [
            (
                item,
                passage(
                    *json.loads(
                        conn.scalar(
                            text("SELECT content FROM paper_texts WHERE text_id=:id"),
                            {"id": item},
                        )
                    )
                ),
            )
            for item in jobs
        ]
        return token, work


def complete(engine, token, results):
    with engine.begin() as conn:
        updated = conn.execute(
            text("""
            UPDATE embeddings SET vector=UNHEX(:value),tokens=:tokens,lease_token=NULL,lease_until=NULL
            WHERE text_id=:id AND recipe=:recipe AND lease_token=:token AND lease_until>UTC_TIMESTAMP(6)
        """),
            [
                dict(
                    id=item,
                    recipe=RECIPE,
                    token=token,
                    value=vector.tobytes().hex(),
                    tokens=length,
                )
                for item, vector, length in results
            ],
        )
        return updated.rowcount


def embed(engine, limit):
    if limit < 1:
        raise ValueError("Embedding limit must be positive")
    encoder = Encoder()
    completed = attempted = 0
    while attempted < limit:
        token, work = claim(engine, min(8, limit - attempted), 120)
        if not work:
            break
        vectors, lengths = encoder.encode([item[1] for item in work])
        completed += complete(
            engine,
            token,
            zip((item[0] for item in work), vectors, lengths, strict=True),
        )
        attempted += len(work)
    return completed
