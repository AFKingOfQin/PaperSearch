# AI-generated code (Codex): durable quarantine before acknowledgement.
from alembic import op

revision = "002_quarantine"
down_revision = "001_revisions"


def upgrade():
    op.execute("""
        CREATE TABLE quarantine (
            group_id VARCHAR(128) NOT NULL, topic VARCHAR(249) NOT NULL,
            partition_id INT NOT NULL, offset_id BIGINT NOT NULL,
            source_location VARCHAR(320) NOT NULL, reason VARCHAR(255) NOT NULL,
            raw MEDIUMBLOB NOT NULL,
            PRIMARY KEY(group_id,topic,partition_id,offset_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """)


def downgrade():
    op.execute("DROP TABLE quarantine")
