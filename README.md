# PaperSearch

PaperSearch is a local arXiv screening app. Kafka carries metadata updates, MySQL stores revisions and screening decisions, and SQLite FTS5 and Parquet snapshots support BM25 and CPU semantic search. A separate local Spark job merges revision histories.

## Start with the published collection

Use Docker Desktop in Linux-container mode. Initial image builds need network access. From this repository in PowerShell:

```powershell
Copy-Item .env.example .env
Add-Content .env 'BASELINE_DIR=D:/PaperSearch-M5/derived/snapshots/c0e77a02d4d94f858ff8c35fe1adbeac'
Add-Content .env 'MODEL_DIR=D:/PaperSearch-M5/models/bge-small-en-v1.5'
docker compose build cli api ui
docker compose up -d --wait mysql kafka
docker compose run --rm --no-deps --entrypoint alembic cli upgrade head
docker compose run --rm --no-deps cli bootstrap /baseline
docker compose up -d --wait api ui
```

Adjust the paths if the published files or model moved. Bootstrap starts on a fresh database. It imports the metadata, seeds the cache with existing vector bytes, and activates the original index when both imports are complete. Repeat the same command to resume an interrupted import. The SQLite index, Parquet files, and model are mounted read-only. Keep their paths configured while the baseline is active. The first launch uses 3,050,173 BM25 papers and 486,123 semantic papers from Cornell arXiv v287.

Open the [reviewer](http://127.0.0.1:18511). Create a project and try `LOOK-M` with BM25 or `vision language model KV cache` with semantic search. Open a result to read its abstract and save a label and note. Export the project's decisions as CSV.

If Docker has exhausted its default address pools, set an unused subnet under `networks.default.ipam.config` in an ignored `compose.override.yaml`. Check existing Docker networks and host routes first. Stop the app with `docker compose --profile '*' stop`.

## Import updates

Put the JSONL in `artifacts/` and supply its container path. Run the consumer concurrently when publishing a large batch.

```powershell
docker compose run --rm --no-deps cli topic papers
$batch = docker compose run --rm --no-deps cli archive /artifacts/updates.jsonl --format arxiv
docker compose run --rm --no-deps cli publish papers $batch
docker compose run --rm --no-deps cli consume papers --drain
docker compose run --rm --no-deps cli snapshot
```

If the lag limit pauses publication, drain the group and repeat `publish` on the same archive. `lag papers` reports uncommitted records per partition. For replay after a topic is recreated, use a fresh topic and group.

An eligible revision queues its title and abstract when the model cache lacks that text. To process pending changes, run `docker compose build embedding`, then `docker compose run --rm --no-deps embedding embed --limit 1024` and publish a new snapshot. The CPU model uses the pinned [BGE recipe](https://huggingface.co/BAAI/bge-small-en-v1.5/tree/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a).

## Develop with the small fixture

Use a fresh Compose project and a separate artifact directory, for example by setting `$env:COMPOSE_PROJECT_NAME='papersearch-fixture'` and `$env:ARTIFACT_DIR='./artifacts/fixture'`. Set unused reviewer ports if the populated app is running. After migrating, skip bootstrap and follow the update workflow with `/fixtures/papers.jsonl --format fixture`. The input has three papers and one malformed line. To revise the river paper, use `/fixtures/updates.jsonl --format fixture`.

Run unit tests with `python -m pip install -e '.[review,test]'` and `python -m pytest`. See the [architecture and integration guide](docs/architecture.md) for Spark and recovery checks.
