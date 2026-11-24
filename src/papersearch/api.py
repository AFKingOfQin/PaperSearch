import csv
import io
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from .database import connect
from .encoder import MAX_TOKENS
from .lexical import search_lexical
from .reviews import (
    CURRENT_DECISIONS,
    ReviewConflict,
    create_project,
    read_decision,
    save_decision,
)
from .semantic import SemanticReader, SemanticUnavailable
from .snapshot import active_snapshot, snapshots_root

app = FastAPI(title="PaperSearch")
engine = connect()
root = snapshots_root()
semantic_reader = SemanticReader()
Paper = Annotated[str, Query(min_length=1, max_length=128)]


class Project(BaseModel):
    topic: str = Field(min_length=1, max_length=1024)
    criteria: str = Field(default="", max_length=8000)


class Decision(BaseModel):
    revision_id: int = Field(gt=0)
    label: Literal["relevant", "irrelevant", "uncertain"]
    note: str = Field(default="", max_length=8000)
    request_id: UUID


def check_project(conn, project, *, lock: Literal["SHARE", "UPDATE"] | None = None):
    query = "SELECT 1 FROM review_projects WHERE project_id=:id"
    if lock is not None:
        query += f" FOR {lock}"
    if (
        conn.scalar(
            text(query),
            {"id": str(project)},
        )
        is None
    ):
        raise HTTPException(404, "Unknown project")


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/status")
def status():
    with engine.connect() as conn:
        generation, _, active = active_snapshot(conn, root)
        metadata = (
            active["coverage"]["metadata"]
            if active and active["generation"] == generation
            else conn.scalar(
                text(
                    "SELECT COUNT(*) FROM papers WHERE current_revision_id IS NOT NULL"
                )
            )
        )
    return dict(generation=generation, metadata=metadata, active=active)


@app.get("/projects")
def projects():
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT project_id,topic,criteria FROM review_projects ORDER BY topic,project_id"
            )
        )
        return [dict(row) for row in rows.mappings()]


@app.post("/projects", status_code=201)
def new_project(body: Project):
    if not body.topic.strip():
        raise HTTPException(422, "Enter a topic")
    return {"project_id": create_project(engine, body.topic.strip(), body.criteria)}


@app.delete("/projects/{project}")
def delete_project(project: UUID):
    params = {"id": str(project)}
    with engine.begin() as conn:
        check_project(conn, project, lock="UPDATE")
        conn.execute(text("DELETE FROM screening_decisions WHERE project_id=:id"), params)
        conn.execute(text("DELETE FROM screening_history WHERE project_id=:id"), params)
        conn.execute(text("DELETE FROM review_projects WHERE project_id=:id"), params)
    return {"project_id": str(project)}


@app.get("/projects/{project}/search")
def search(
    project: UUID,
    q: Annotated[str, Query(min_length=1, max_length=512)],
    ranker: Literal["bm25", "semantic"] = "bm25",
    field: Literal["all", "title", "abstract"] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    snapshot: str | None = None,
):
    with engine.connect() as conn:
        check_project(conn, project)
        _, folder, manifest = active_snapshot(conn, root)
    if manifest is None:
        raise HTTPException(503, "Publish a snapshot to enable search")
    snapshot_id = manifest["snapshot_id"]
    if snapshot is not None and snapshot != snapshot_id:
        raise HTTPException(409, "A new snapshot is active. Start the search again.")
    if ranker == "semantic" and field != "all":
        raise HTTPException(422, "Semantic search uses both title and abstract")
    served = ranker
    tokens = fallback_reason = None
    try:
        if ranker == "semantic":
            try:
                hits, more, tokens = semantic_reader.search(
                    folder, manifest, q, offset, limit
                )
            except SemanticUnavailable as exc:
                served, fallback_reason = "bm25", str(exc)
        if served == "bm25":
            hits, more = search_lexical(
                folder / "lexical.sqlite",
                q,
                field,
                offset,
                limit,
                baseline=manifest.get("format_version") == 2,
            )
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return dict(
        results=hits,
        has_more=more,
        snapshot_id=snapshot_id,
        coverage=manifest["coverage"],
        ranker=served,
        requested_ranker=ranker,
        fallback_reason=fallback_reason,
        query_truncated=tokens is not None and tokens > MAX_TOKENS,
    )


@app.get("/papers/detail")
def detail(paper: Paper, revision_id: Annotated[int, Query(gt=0)]):
    with engine.connect() as conn:
        selected = conn.execute(
            text("""
            SELECT r.payload,p.current_revision_id FROM revisions r JOIN papers p USING(paper_id)
            WHERE r.paper_id=:paper AND r.revision_id=:revision
        """),
            dict(paper=paper, revision=revision_id),
        ).first()
        if selected is None:
            raise HTTPException(404, "Unknown paper revision")
        revisions = conn.execute(
            text("""
            SELECT revision_id,version_rank,source_updated_at FROM revisions
            WHERE paper_id=:paper ORDER BY version_rank DESC,source_updated_at DESC,revision_id
        """),
            {"paper": paper},
        ).mappings()
        return dict(
            payload=json.loads(selected.payload),
            current_revision_id=selected.current_revision_id,
            revisions=[dict(row) for row in revisions],
        )


@app.put("/projects/{project}/decision")
def decide(project: UUID, paper: Paper, body: Decision):
    with engine.begin() as conn:
        check_project(conn, project, lock="SHARE")
        try:
            history = save_decision(
                conn,
                str(project),
                paper,
                body.revision_id,
                body.label,
                body.note,
                str(body.request_id),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ReviewConflict as exc:
            raise HTTPException(409, str(exc)) from exc
    return {"history_id": history}


@app.get("/projects/{project}/decision")
def decision(project: UUID, paper: Paper):
    with engine.connect() as conn:
        check_project(conn, project)
        return read_decision(conn, str(project), paper)


@app.get("/projects/{project}/export.csv")
def export(project: UUID):
    with engine.connect() as conn:
        check_project(conn, project)

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            (
                "paper_id",
                "history_id",
                "revision_id",
                "label",
                "note",
                "saved_at",
                "needs_reconsideration",
            )
        )
        yield buffer.getvalue()
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as conn:
            after = ""
            while page := conn.execute(
                text(
                    CURRENT_DECISIONS
                    + " AND d.paper_id>:after ORDER BY d.paper_id LIMIT 128"
                ),
                dict(project=str(project), after=after),
            ).all():
                buffer.seek(0)
                buffer.truncate()
                writer.writerows(page)
                yield buffer.getvalue()
                after = page[-1].paper_id

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="screening-{project}.csv"'
        },
    )
