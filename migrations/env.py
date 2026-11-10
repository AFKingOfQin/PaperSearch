# AI-generated code (Codex): Alembic runtime.
from alembic import context

from papersearch.database import connect

with connect().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
