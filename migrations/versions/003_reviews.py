# AI-generated code (Codex): snapshot pointer and revision-aware review.
from alembic import op

revision = "003_reviews"
down_revision = "002_quarantine"

TABLES = {
    "review_projects": """
        project_id CHAR(36) PRIMARY KEY,
        topic VARCHAR(1024) NOT NULL,
        criteria TEXT NOT NULL
    """,
    "screening_history": """
        history_id BIGINT AUTO_INCREMENT PRIMARY KEY,
        project_id CHAR(36) NOT NULL,
        paper_id VARCHAR(128) NOT NULL,
        revision_id BIGINT NOT NULL,
        label ENUM('relevant','irrelevant','uncertain') NOT NULL,
        note TEXT NOT NULL,
        request_id CHAR(36) NOT NULL,
        saved_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        UNIQUE(project_id,paper_id,request_id),
        FOREIGN KEY(project_id) REFERENCES review_projects(project_id),
        FOREIGN KEY(paper_id) REFERENCES papers(paper_id),
        FOREIGN KEY(revision_id) REFERENCES revisions(revision_id)
    """,
    "screening_decisions": """
        project_id CHAR(36) NOT NULL,
        paper_id VARCHAR(128) NOT NULL,
        history_id BIGINT NOT NULL REFERENCES screening_history(history_id),
        PRIMARY KEY(project_id,paper_id)
    """,
}


def upgrade():
    op.execute("ALTER TABLE pipeline_state ADD COLUMN active_snapshot CHAR(32) NULL")
    for name, columns in TABLES.items():
        op.execute(
            f"CREATE TABLE {name} ({columns}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
        )


def downgrade():
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE {name}")
    op.execute("ALTER TABLE pipeline_state DROP COLUMN active_snapshot")
