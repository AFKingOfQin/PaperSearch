# AI-generated code (Codex): real Kafka, MySQL, snapshots, reviewer, and Spark checks.
import argparse
import os
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pyarrow.parquet as pq
import requests
from kafka import KafkaConsumer
from sqlalchemy import text

from papersearch import snapshot, stream
from papersearch.database import apply_revision, connect
from papersearch.embeddings import backfill, claim, complete, embed
from papersearch.encoder import DIM
from papersearch.history import export_history
from papersearch.records import parse_record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROOT = Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
BASE = os.environ.get("PAPERSEARCH_API", "http://api:8000")
PROJECT = "PaperSearch integration"
RIVER = "fixture:river"


def call(method, path, **kwargs):
    response = requests.request(method, BASE + path, timeout=90, **kwargs)
    response.raise_for_status()
    return response


def live_scalar(engine, statement):
    with engine.connect() as conn:
        return conn.scalar(text(statement))


def apply(engine, revision):
    with engine.begin() as conn:
        return apply_revision(conn, revision)


def verify_review():
    (project,) = [p for p in call("GET", "/projects").json() if p["topic"] == PROJECT]
    prefix = "/projects/" + project["project_id"]
    decision = call("GET", prefix + "/decision", params={"paper": RIVER}).json()
    assert len(decision["history"]) == 1
    current = decision["current"]
    assert current["label"] == "relevant" and current["needs_reconsideration"]
    assert "screened before revision" in call("GET", prefix + "/export.csv").text


def run():
    engine = connect()
    topic = "verify-" + uuid4().hex[:12]
    stream.init_topic(topic)
    folder = stream.archive((FIXTURES / "papers.jsonl"), ROOT, "fixture")
    try:
        stream.publish(folder, topic, max_lag=2)
    except ValueError as error:
        assert "lag limit" in str(error)
    else:
        raise AssertionError("Expected the bounded publisher to pause")
    with patch.object(
        KafkaConsumer, "commit", side_effect=RuntimeError("stop before acknowledgement")
    ):
        try:
            stream.consume(engine, topic, drain=True)
        except RuntimeError as error:
            assert str(error) == "stop before acknowledgement"
        else:
            raise AssertionError(
                "Expected to interrupt a delivery after MySQL committed"
            )
    with closing(stream.group_reader(stream.GROUP)) as reader:
        assert sum(stream.offsets(reader, topic).values()) == 2
    stream.consume(engine, topic, drain=True)
    stream.publish(folder, topic)
    stream.consume(engine, topic, drain=True)
    assert (
        live_scalar(engine, f"SELECT COUNT(*) FROM quarantine WHERE topic='{topic}'")
        == 1
    )
    baseline = live_scalar(engine, "SELECT COUNT(*) FROM revisions")
    stream.publish(folder, topic, replay=True)
    stream.consume(engine, topic, drain=True)
    assert live_scalar(engine, "SELECT COUNT(*) FROM revisions") == baseline

    originals = (FIXTURES / "papers.jsonl").read_bytes().splitlines()
    river = parse_record(originals[0], "fixture")
    backfill(engine)
    embed(engine, 64)
    before = snapshot.publish_snapshot(engine, snapshot.snapshots_root())
    assert before["coverage"]["semantic"] == before["coverage"]["lexical"] == 3
    project = call("POST", "/projects", json={"topic": PROJECT}).json()["project_id"]
    prefix = "/projects/" + project
    page = call(
        "GET", prefix + "/search", params={"q": "river", "ranker": "semantic"}
    ).json()
    assert any(row["paper_id"] == RIVER for row in page["results"])
    hit = call("GET", prefix + "/search", params={"q": "river"}).json()["results"][0]
    body = dict(
        revision_id=hit["revision_id"],
        label="relevant",
        note="screened before revision",
        request_id=str(uuid4()),
    )
    assert hit["paper_id"] == RIVER
    saved = call("PUT", prefix + "/decision", params={"paper": RIVER}, json=body).json()
    assert (
        saved
        == call("PUT", prefix + "/decision", params={"paper": RIVER}, json=body).json()
    )

    with patch.object(
        snapshot, "pages", side_effect=RuntimeError("interrupt snapshot")
    ):
        try:
            snapshot.publish_snapshot(engine, snapshot.snapshots_root())
        except RuntimeError as error:
            assert str(error) == "interrupt snapshot"
    assert (
        call("GET", "/status").json()["active"]["snapshot_id"] == before["snapshot_id"]
    )

    embeddings_before = live_scalar(engine, "SELECT COUNT(*) FROM embeddings")
    apply(engine, replace(river, paper_id="fixture:copy"))
    assert live_scalar(engine, "SELECT COUNT(*) FROM embeddings") == embeddings_before
    conflict = replace(river, paper_id="fixture:conflict")
    old, _ = apply(engine, conflict)
    apply(engine, replace(conflict, version_rank=2))
    withdrawn = replace(river, paper_id="fixture:withdrawn")
    apply(engine, withdrawn)
    base_path = ROOT / "batch" / "base.parquet"
    export_history(engine, base_path)
    watermark = live_scalar(engine, "SELECT MAX(revision_id) FROM revisions")

    alter = replace(river.payload, title="A conflicting title")
    assert (
        apply(engine, replace(conflict, version_rank=2, payload=alter))[1] == "conflict"
    )
    assert (
        live_scalar(
            engine,
            "SELECT current_revision_id FROM papers WHERE paper_id='fixture:conflict'",
        )
        == old
    )
    assert apply(engine, replace(withdrawn, payload=alter))[1] == "conflict"
    apply(engine, replace(river, paper_id="fixture:new"))
    update = stream.archive((FIXTURES / "updates.jsonl"), ROOT, "fixture")
    stream.publish(update, topic)
    stream.consume(engine, topic, drain=True)
    assert apply(engine, replace(river, version_rank=0))[1] == "stale"
    pending = snapshot.publish_snapshot(engine, snapshot.snapshots_root())
    folder = snapshot.snapshots_root() / pending["snapshot_id"]
    vector_rows = set(pq.read_table(folder / "semantic.parquet")["row_id"].to_pylist())
    river_row = next(
        row
        for row in pq.read_table(folder / "corpus.parquet").to_pylist()
        if row["paper_id"] == RIVER
    )
    assert river_row["row_id"] not in vector_rows
    assert river_row["revision_id"] != hit["revision_id"]
    stale_page = requests.get(
        BASE + prefix + "/search",
        params={"q": "river", "snapshot": before["snapshot_id"]},
        timeout=30,
    )
    assert stale_page.status_code == 409

    token, jobs = claim(engine, 8, 120)
    assert jobs
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE embeddings SET lease_until=UTC_TIMESTAMP(6) WHERE lease_token=:token"
            ),
            {"token": token},
        )
    new_token, reclaimed = claim(engine, 8, 120)
    assert reclaimed == jobs
    assert complete(engine, token, [(jobs[0][0], np.zeros(DIM, dtype="<f4"), 2)]) == 0
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE embeddings SET lease_until=UTC_TIMESTAMP(6) WHERE lease_token=:token"
            ),
            {"token": new_token},
        )
    assert embed(engine, 64) >= len(jobs)
    after = snapshot.publish_snapshot(engine, snapshot.snapshots_root())
    assert after["coverage"]["semantic"] == after["coverage"]["lexical"]
    verify_review()
    export_history(engine, ROOT / "batch" / "updates.parquet", watermark)
    print(
        "Kafka replay, durable decisions, snapshot publication, and CPU leases passed"
    )


def verify_spark():
    result = {
        row["paper_id"]: row
        for row in pq.read_table(ROOT / "batch" / "merged").to_pylist()
    }
    assert {
        paper: result["fixture:" + paper]["change"]
        for paper in ("new", "river", "withdrawn", "vision", "conflict")
    } == {
        "new": "new",
        "river": "changed",
        "withdrawn": "withdrawn",
        "vision": "unchanged",
        "conflict": "changed",
    }
    with connect().connect() as conn:
        winners = conn.execute(
            text("""
            SELECT p.paper_id,r.version_rank,r.source_updated_at,r.payload
            FROM papers p JOIN revisions r ON r.revision_id=p.current_revision_id
        """)
        ).mappings()
        expected = {
            row["paper_id"]: (
                row["version_rank"],
                row["source_updated_at"],
                row["payload"].decode(),
            )
            for row in winners
        }
    assert {
        paper: tuple(
            row["current"][field]
            for field in ("version_rank", "source_updated_at", "payload")
        )
        for paper, row in result.items()
        if row["current"] is not None
    } == expected
    print("Spark and MySQL revision winners match")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("check", choices=["pipeline", "restart", "spark"])
    {"pipeline": run, "restart": verify_review, "spark": verify_spark}[
        parser.parse_args().check
    ]()
