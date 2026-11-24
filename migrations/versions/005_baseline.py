# AI-generated code (Codex): checkpointed import of published metadata and vectors.
from alembic import op

revision = "005_baseline"
down_revision = "004_embeddings"


def upgrade():
    op.execute("""
        CREATE TABLE baseline_import (
            id INT PRIMARY KEY,
            source_id CHAR(32),
            corpus_row BIGINT NOT NULL DEFAULT 0,
            vector_row BIGINT NOT NULL DEFAULT 0,
            complete BOOLEAN NOT NULL DEFAULT FALSE
        ) ENGINE=InnoDB
    """)
    op.execute("INSERT INTO baseline_import(id) VALUES(1)")


def downgrade():
    op.execute("DROP TABLE baseline_import")
