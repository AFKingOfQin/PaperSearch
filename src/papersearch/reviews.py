from uuid import uuid4

from sqlalchemy import text


class ReviewConflict(ValueError):
    pass


def create_project(engine, topic, criteria):
    project = str(uuid4())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO review_projects VALUES(:id,:topic,:criteria)"),
                     dict(id=project, topic=topic, criteria=criteria))
    return project


def save_decision(conn, project, paper, revision, label, note, request):
    args = dict(project=project, paper=paper, revision=revision, label=label, note=note, request=request)
    if conn.scalar(text("SELECT paper_id FROM papers WHERE paper_id=:paper FOR UPDATE"), args) is None:
        raise LookupError("Unknown paper")
    if conn.scalar(text("SELECT revision_id FROM revisions WHERE revision_id=:revision AND paper_id=:paper"), args) is None:
        raise ReviewConflict("The revision does not belong to this paper.")
    previous = conn.execute(text("""
        SELECT history_id,revision_id,label,note FROM screening_history
        WHERE project_id=:project AND paper_id=:paper AND request_id=:request
    """), args).first()
    if previous:
        if tuple(previous[1:]) != (revision, label, note):
            raise ReviewConflict("Decision request ID was reused with different content.")
        return previous.history_id
    history = conn.execute(text("""
        INSERT INTO screening_history(project_id,paper_id,revision_id,label,note,request_id)
        VALUES(:project,:paper,:revision,:label,:note,:request)
    """), args).lastrowid
    conn.execute(text("""
        INSERT INTO screening_decisions VALUES(:project,:paper,:history)
        ON DUPLICATE KEY UPDATE history_id=:history
    """), {**args, "history": history})
    return history


CURRENT_DECISIONS = """
    SELECT d.paper_id,h.history_id,h.revision_id,h.label,h.note,h.saved_at,
           NOT (reviewed.text_id <=> live.text_id) AS needs_reconsideration
    FROM screening_decisions d
    JOIN screening_history h ON h.history_id=d.history_id
    JOIN revisions reviewed ON reviewed.revision_id=h.revision_id
    JOIN papers p ON p.paper_id=d.paper_id
    LEFT JOIN revisions live ON live.revision_id=p.current_revision_id
    WHERE d.project_id=:project
"""


def read_decision(conn, project, paper):
    args = dict(project=project, paper=paper)
    current = conn.execute(text(CURRENT_DECISIONS + " AND d.paper_id=:paper"), args).mappings().first()
    history = conn.execute(text("""
        SELECT history_id,revision_id,label,note,saved_at FROM screening_history
        WHERE project_id=:project AND paper_id=:paper ORDER BY history_id
    """), args).mappings()
    return dict(current=dict(current) if current else None, history=[dict(row) for row in history])
