# PaperSearch

PaperSearch is a local paper-screening app. Kafka delivers arXiv metadata updates, MySQL keeps revision and decision history, and published SQLite and Parquet snapshots support BM25 and CPU semantic search. A local Spark job independently merges revision histories.

## Run the offline fixture

Use Docker Desktop with Linux containers and Docker Compose. The initial image builds need network access. In PowerShell from the repo root:

```powershell
Copy-Item .env.example .env
docker compose up -d --wait mysql kafka
docker compose build cli api ui
docker compose run --rm --no-deps --entrypoint alembic cli upgrade head
docker compose run --rm --no-deps cli topic papers
$batch = docker compose run --rm --no-deps cli archive /fixtures/papers.jsonl --format fixture
docker compose run --rm --no-deps cli publish papers $batch
docker compose run --rm --no-deps cli consume papers --drain
docker compose run --rm --no-deps cli snapshot
docker compose up -d api ui
```

Open the [reviewer](http://127.0.0.1:18510). Create a project, search for `river`, and save a label and note. The sample has three valid papers and one malformed input. Run `docker compose run --rm --no-deps cli publish papers $batch --replay` followed by `consume papers --drain` to replay the batch. Use `/fixtures/updates.jsonl` in the same archive, publish, consume, and snapshot sequence to see the river revision. The original decision remains in history and is flagged for reconsideration.

For an arXiv JSONL dump, put the file in `artifacts/`, pass its container path under `/artifacts/` to `archive`, and use `--format arxiv`. On a large batch, run `consume papers` in a second terminal while publishing. If the lag limit pauses publication, run the consumer and repeat `publish` on the same archive. Use `lag papers` to view uncommitted records per partition.

If Docker reports exhausted address pools, add an untracked `compose.override.yaml` with an unused local subnet under `networks.default.ipam.config`. Check existing Docker networks and host routes before choosing it. To stop the app and keep its MySQL and Kafka volumes, run `docker compose stop`.

## Enable CPU semantic search

Place `model.onnx` from the `onnx/` directory and `tokenizer.json` in `artifacts/models/bge-small-en-v1.5/`. The application uses the pinned CPU recipe and loads these files locally. [BGE model files](https://huggingface.co/BAAI/bge-small-en-v1.5/tree/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a)

```powershell
docker compose build embedding
docker compose run --rm --no-deps embedding embed --limit 1024
docker compose run --rm --no-deps cli snapshot
```

Select **semantic** in the reviewer. New eligible revisions queue automatically. Use `embed --backfill` when adding a recipe to a database that already has rows. Each run processes a bounded number of jobs. The reviewer displays current, lexical, and semantic counts.

## Spark and tests

Export full history with `docker compose run --rm --no-deps cli export-history /artifacts/batch/base.parquet`. Supply this and a Parquet export of incoming revisions to Spark. For a delta from the same database, stop ingestion before taking the base export and recording its maximum revision ID, then pass that ID to `export-history --after-revision` after the next import. Revision IDs are local to each database. The merge compares normalized contents.

```powershell
docker compose run --rm --no-deps spark --master 'local[2]' --driver-memory 1g --conf spark.sql.shuffle.partitions=4 --conf spark.ui.enabled=false /jobs/spark_merge.py /artifacts/batch/base.parquet /artifacts/batch/updates.parquet /artifacts/batch/merged
python -m pip install -e '.[test]'
python -m pytest
```

The [architecture guide](docs/architecture.md) describes the data flow, CS544 concepts, and real-service verification.
