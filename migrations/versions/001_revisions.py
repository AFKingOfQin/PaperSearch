# AI-generated code (Codex): canonical paper and normalized text tables.
from alembic import op

revision = "001_revisions"
down_revision = None

TABLES = {
    "text_prefixes": "prefix VARBINARY(64) PRIMARY KEY",
    "paper_texts": """
        text_id BIGINT AUTO_INCREMENT PRIMARY KEY,
        prefix VARBINARY(64) NOT NULL REFERENCES text_prefixes(prefix),
        content MEDIUMBLOB NOT NULL,
        INDEX(prefix)
    """,
    "papers": """
        paper_id VARCHAR(128) PRIMARY KEY,
        current_revision_id BIGINT NULL
    """,
    "revisions": """
        revision_id BIGINT AUTO_INCREMENT PRIMARY KEY,
        paper_id VARCHAR(128) NOT NULL,
        version_rank INT NOT NULL,
        source_updated_at CHAR(27) NOT NULL,
        payload MEDIUMBLOB NOT NULL,
        text_id BIGINT NOT NULL,
        INDEX(paper_id,version_rank,source_updated_at),
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id),
        FOREIGN KEY (text_id) REFERENCES paper_texts(text_id)
    """,
    "pipeline_state": """
        id INT PRIMARY KEY,
        generation BIGINT NOT NULL DEFAULT 0
    """,
}


def upgrade():
    for name, columns in TABLES.items():
        op.execute(f"CREATE TABLE {name} ({columns}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")
    op.execute("INSERT INTO pipeline_state(id) VALUES(1)")


def downgrade():
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE {name}")
