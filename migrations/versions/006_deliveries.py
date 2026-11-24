# AI-generated code (Codex): successful Kafka deliveries committed with metadata.
from alembic import op

revision = "006_deliveries"
down_revision = "005_baseline"


def upgrade():
    op.execute("""
        CREATE TABLE processed_deliveries (
            group_id VARCHAR(128) NOT NULL,
            topic VARCHAR(249) NOT NULL,
            partition_id INT NOT NULL,
            offset_id BIGINT NOT NULL,
            PRIMARY KEY(group_id,topic,partition_id,offset_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """)


def downgrade():
    op.execute("DROP TABLE processed_deliveries")
