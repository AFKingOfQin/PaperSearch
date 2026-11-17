# From JSONL to a screening decision

1. **Kafka and replay.** Archive copies input into a private directory, then names the finished batch. Publish uses paper IDs as partition keys, sends bounded windows, and checkpoints only after the broker acknowledges every message in the window. Resume uses the same immutable archive and topic. If you recreate the topic or lose a retained range, use a fresh topic and group and replay the needed archives. Run one publisher per archive and topic.
2. **MySQL and transactions.** The consumer records a durable outcome before committing the Kafka offset. A transaction serializes revisions for one paper. Earlier versions remain in history, identical deliveries reuse their existing revision, and conflicting payloads at one precedence disqualify that precedence. Each normalized text gets one ID, with exact bytes compared under a database lock. Decisions record the revision ID and retain the previous saves.
3. **Caching and publication.** A bounded worker claims eligible text using database-clock leases. The job and vector live in the same SQL row. The lease token fences completion after reclaim. A snapshot reads current revisions and matching vectors in one repeatable-read transaction, assigns shared row IDs, and activates the finished files with a conditional MySQL pointer update. Search reads that immutable publication. A decision is flagged if the current text ID differs from the reviewed text ID.
4. **Spark and Parquet.** A separate local Spark workload uses DataFrame deduplication, grouping, and a full outer join. It selects winners from the complete base revision history and new events, then computes changes. The Spark path does not replace the live transaction path.

This maps to CS544 concepts in container orchestration, SQL concurrency, Kafka partitions and offsets, cached derived work, Parquet columnar storage, and Spark DataFrame execution. Everything runs on one machine.

## Run the integration check

Use a fresh Compose project and empty artifact directory with the local model files present. Set `COMPOSE_PROJECT_NAME` and `ARTIFACT_DIR` to those test locations if your usual app is populated. Follow the README setup through building the images, migrating and starting the API. The integration test handles its own fixture import and snapshot construction. Build the embedding image before running the check.

```powershell
$tests = (Resolve-Path tests).Path
docker compose run --rm --no-deps -v "${tests}:/tests:ro" --entrypoint python embedding /tests/integration/verify_pipeline.py pipeline
docker compose restart mysql kafka api
docker compose up -d --wait mysql kafka api
docker compose run --rm --no-deps -v "${tests}:/tests:ro" --entrypoint python embedding /tests/integration/verify_pipeline.py restart
docker compose run --rm --no-deps spark --master 'local[2]' --driver-memory 1g --conf spark.sql.shuffle.partitions=4 --conf spark.ui.enabled=false /jobs/spark_merge.py /artifacts/batch/base.parquet /artifacts/batch/updates.parquet /artifacts/batch/merged
docker compose run --rm --no-deps -v "${tests}:/tests:ro" --entrypoint python embedding /tests/integration/verify_pipeline.py spark
```
