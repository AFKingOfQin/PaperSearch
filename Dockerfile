FROM python:3.14.4-slim-bookworm AS core
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY src src
COPY migrations migrations
RUN python -m pip install --no-cache-dir .
ENTRYPOINT ["papersearch"]

FROM core AS review
RUN python -m pip install --no-cache-dir '.[review]'
