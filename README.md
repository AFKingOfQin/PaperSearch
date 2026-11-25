# PaperSearch

PaperSearch is a local app for finding and screening arXiv papers. Search titles and abstracts with BM25 keyword ranking or semantic ranking, then organize results into review projects. Each project can save labels and notes on paper revisions and export its decisions as a CSV.

## How it works

1. **Ingest.** The CLI archives JSONL batches and publishes records to Kafka. A consumer validates each record, writes paper revisions to MySQL, and commits its Kafka offset after the database write succeeds.
2. **Index.** Snapshot publication builds a SQLite FTS5 index for BM25 search. A CPU worker can generate BGE embeddings for eligible papers, which the snapshot stores in Parquet for semantic search.
3. **Review.** The Streamlit reviewer searches the active snapshot through the API and saves screening decisions against specific revisions in MySQL.

A separate Spark job merges revision histories in Parquet for batch processing. See the [architecture and integration guide](docs/architecture.md) for the data flow, recovery checks, and Spark commands.

## Run PaperSearch locally

Install Docker with Compose and start it. Use Linux containers on Windows. The first build needs internet access to download container images and Python dependencies.

```sh
git clone https://github.com/AFKingOfQin/PaperSearch.git
cd PaperSearch
```

### Run the bundled demo

The clone includes [three synthetic papers](tests/fixtures/papers.jsonl) and a deliberately malformed row that exercises the ingestion pipeline. The commands below import the fixture, build a BM25 index, and start the reviewer. You can run them without a separate dataset or model download.

#### PowerShell

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build cli api ui
docker compose up -d --wait mysql kafka
docker compose run --rm --no-deps --entrypoint alembic cli upgrade head
docker compose run --rm --no-deps cli topic papers
$batch = docker compose run --rm --no-deps cli archive /fixtures/papers.jsonl --format fixture
docker compose run --rm --no-deps cli publish papers $batch
docker compose run --rm --no-deps cli consume papers --drain
docker compose run --rm --no-deps cli snapshot
docker compose up -d --wait api ui
```

#### Bash or Zsh

```sh
test -f .env || cp .env.example .env
docker compose build cli api ui
docker compose up -d --wait mysql kafka
docker compose run --rm --no-deps --entrypoint alembic cli upgrade head
docker compose run --rm --no-deps cli topic papers
batch=$(docker compose run --rm --no-deps cli archive /fixtures/papers.jsonl --format fixture)
docker compose run --rm --no-deps cli publish papers "$batch"
docker compose run --rm --no-deps cli consume papers --drain
docker compose run --rm --no-deps cli snapshot
docker compose up -d --wait api ui
```

Open the [reviewer](http://127.0.0.1:18511), create a project, and search for `river` with **bm25** ranking. Open **River graph models**, save a label and note, and use **Export decisions (CSV)**.

Stop the demo with `docker compose stop ui api kafka mysql`. Start it again with `docker compose up -d --wait mysql kafka api ui`. Review decisions and the snapshot persist across stops.

If either default port is occupied, set `REVIEW_UI_PORT` and `REVIEW_API_PORT` to unused ports in `.env` and open the configured UI port. If Docker reports that its default address pools are exhausted, check your Docker networks and host routes, then set an unused subnet under `networks.default.ipam.config` in an ignored `compose.override.yaml`.

### Enable semantic search in the demo

Save the [pinned BGE ONNX model](https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/onnx/model.onnx) and [tokenizer](https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/tokenizer.json) as `model.onnx` and `tokenizer.json` in `artifacts/models/bge-small-en-v1.5/`. If you set `MODEL_DIR` in `.env`, use that directory instead. Then run:

```sh
docker compose build embedding
docker compose run --rm --no-deps embedding embed --limit 1024
docker compose run --rm --no-deps cli snapshot
```

Choose **semantic** ranking in the reviewer and try `river flow`. Rerun the worker and publish a snapshot after ingesting updates whose text needs embeddings.

### Use a prepared arXiv collection

The Cornell arXiv v287 snapshot provides **3,050,173 papers for BM25** and **486,123 vectors for semantic search**. Download the 9.1 GB bundle from the [arXiv v287 GitHub Release](https://github.com/AFKingOfQin/PaperSearch/releases/tag/arxiv-v287), or use a copy of the same snapshot someone has shared with you.

#### Assemble the snapshot

Download all five files, `papersearch-arxiv-v287.tar.part01` through `papersearch-arxiv-v287.tar.part05`, into the same directory and run the commands there. Allow about 28 GB for the parts, reassembled archive, and extracted snapshot, plus space for MySQL.

PowerShell

```powershell
cmd.exe /c 'copy /b papersearch-arxiv-v287.tar.part01+papersearch-arxiv-v287.tar.part02+papersearch-arxiv-v287.tar.part03+papersearch-arxiv-v287.tar.part04+papersearch-arxiv-v287.tar.part05 papersearch-arxiv-v287.tar'
New-Item -ItemType Directory -Force arxiv-v287 | Out-Null
tar -xf papersearch-arxiv-v287.tar -C arxiv-v287
```

Bash or Zsh

```sh
cat papersearch-arxiv-v287.tar.part0[1-5] > papersearch-arxiv-v287.tar
mkdir -p arxiv-v287
tar -xf papersearch-arxiv-v287.tar -C arxiv-v287
```

#### Load the snapshot

Use a fresh database for bootstrap. If the demo is already set up, use a separate Compose project (`COMPOSE_PROJECT_NAME`), artifact directory (`ARTIFACT_DIR`), and ports in a separate checkout.

In the repository, copy `.env.example` to `.env` if needed. Set `BASELINE_DIR` to the extracted directory containing `manifest.json`, `lexical.sqlite`, `corpus.parquet`, and `semantic.parquet`. You can use an absolute path or put the directory at `./artifacts/arxiv-v287` and set `BASELINE_DIR=./artifacts/arxiv-v287`. Use the pinned BGE model and tokenizer described above to enable semantic search.

```sh
docker compose build cli api ui
docker compose up -d --wait mysql kafka
docker compose run --rm --no-deps --entrypoint alembic cli upgrade head
docker compose run --rm --no-deps cli bootstrap /baseline
docker compose up -d --wait api ui
```

Bootstrap checks the snapshot files against the manifest, imports the metadata and existing vectors, and activates the original index. Repeat the command to resume an interrupted import. Keep the extracted snapshot available while it is active. In the reviewer, try `LOOK-M` with BM25 or `vision language model KV cache` with semantic ranking.

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

An eligible revision queues its title and abstract when the model cache lacks that text. Use the [embedding steps above](#enable-semantic-search-in-the-demo) to process pending changes and publish a new snapshot.

## Development checks

To try a revision in the demo, follow the update workflow with `/fixtures/updates.jsonl --format fixture` to revise the river paper.

Run unit tests with `python -m pip install -e '.[review,test]'` and `python -m pytest`.

## AI

The [AI transcripts](docs/AI-Transcripts/) cover project scoping, architecture, implementation planning, code review, testing, and search quality improvements.
