# AI-generated code (Codex): embedding jobs with lease and vector in the same row.
from alembic import op

revision = "004_embeddings"
down_revision = "003_reviews"


def upgrade():
    op.execute("""
        CREATE TABLE embeddings (
            text_id BIGINT NOT NULL, recipe VARCHAR(200) NOT NULL,
            vector VARBINARY(1536), tokens INT,
            lease_token CHAR(36), lease_until DATETIME(6),
            PRIMARY KEY(text_id,recipe),
            INDEX(recipe,lease_until,text_id),
            FOREIGN KEY(text_id) REFERENCES paper_texts(text_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """)


def downgrade():
    op.execute("DROP TABLE embeddings")
