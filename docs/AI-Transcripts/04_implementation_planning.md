# PaperSearch — Implementation Planning

## User

Now that we have the architecture of the project, can you give me a detailed plan for how we should implement it? I want to divide the project into several phases and make sure each part works as expected before moving on to the next one.

## ChatGPT

I would divide the implementation into ten milestones, from M0 to M9. The first few milestones establish the data pipeline, the middle milestones build the search and screening application, and the final milestones focus on batch processing, evaluation, and making the project reproducible.

| Milestone | Main objective |
| --- | --- |
| M0 | Set up the development environment and infrastructure |
| M1 | Define and implement paper-processing rules |
| M2 | Implement persistent metadata and screening storage in MySQL |
| M3 | Implement interruption-safe Kafka ingestion and replay |
| M4 | Implement derived-data processing and Parquet snapshots |
| M5 | Build BM25 search and the end-to-end reviewer application |
| M6 | Implement CPU-based semantic search and retrieval evaluation |
| M7 | Implement and evaluate the Spark batch-processing workflow |
| M8 | Run reproducible correctness and performance experiments |
| M9 | Complete documentation, integration verification, and the demo |

I would initially use a small offline fixture throughout these milestones. Once the complete system works, we can gradually increase the size of the dataset. Implementation progress and dataset size should be treated as separate milestones.

## User

Can you explain more about what we need to do for each milestone? Also, for each milestone, I want to know how I can verify that it is actually complete. I don't want to find out at the end that one of the earlier parts wasn't working properly.

## ChatGPT

Each milestone should have implementation tasks, a demonstration or test, and evidence that the expected behavior was observed. Here is how I would break them down.

### M0 — Environment and infrastructure

Set up the repository, Python environment, Docker Compose configuration, and local storage paths. Configure Kafka and MySQL, including persistent volumes and an `.env.example` file for configuration.

Provide a simple diagnostic command that checks required dependencies and service connectivity. Keep the setup instructions in the README so they can be followed from a fresh checkout.

**Completion criteria:**

- Docker Compose configuration is valid and both services can start.
- A real MySQL connection can execute a simple query.
- A Kafka test message can be published and consumed.
- Required Python dependencies can be installed using the documented procedure.

Save the actual setup and smoke-test results. A diagnostic script that only checks whether configuration values exist is not enough to establish that the services work.

### M1 — Paper inputs and processing rules

Define a common representation for paper metadata. Implement parsing for the offline fixture and arXiv JSONL input, including validation, stable paper identifiers, normalized source versions, and update information.

Create a small fixture containing new papers, exact duplicates, newer revisions, older revisions, conflicting records, and invalid input. Define the expected behavior of the processing rules before introducing a database or Kafka.

It would also be useful to have a small reference processor that applies the rules in memory. We can use its output to check the database and Spark implementations later.

**Completion criteria:**

- Valid records are normalized consistently.
- Different versions of the same arXiv paper map to the same stable paper ID.
- Invalid records and ambiguous version information have a documented handling policy.
- The reference processor produces the expected results on controlled fixtures.

### M2 — MySQL persistence

Create the database schema and implement the storage operations for paper metadata, accepted revisions, screening projects, and screening decisions.

Make revision processing transactional. The database should recognize an exact replay, retain newer current metadata when an older record arrives, and handle content conflicts at the same source version and timestamp according to the policy established in M1.

Implement operations to create screening projects, save decisions and notes, retrieve the latest decision, and preserve decision history.

**Completion criteria:**

- Repeated imports do not produce duplicate canonical papers or duplicate identical revisions.
- A valid newer revision updates the current paper without deleting existing screening decisions.
- An older revision does not replace newer metadata.
- Screening decisions remain available after reconnecting to the database or restarting the application.
- The final database state agrees with the expected fixture results.

Test these operations against a real MySQL instance as well as through unit tests.

### M3 — Kafka ingestion and replay

Implement the producer and consumer. The producer should archive the input batch, send records to Kafka using stable paper IDs as message keys, and save a checkpoint after each acknowledged publication window.

The consumer should validate incoming records, apply the M2 database operations, and commit offsets only after the corresponding records have been successfully handled. Define how malformed messages are reported and ensure an unsuccessful record is not silently lost by committing a later offset.

Provide commands to resume an interrupted import and explicitly replay an archived batch.

**Completion criteria:**

- Importing the fixture through Kafka produces the expected database records.
- Interrupting and resuming the producer does not lose records.
- Interrupting the consumer and restarting it allows processing to recover.
- Reprocessing records after a database commit but before an offset commit does not duplicate their effects.
- Explicitly replaying an already processed batch leaves the expected canonical state unchanged.

### M4 — Derived processing and Parquet snapshots

Implement a workflow that exports the appropriate paper records into Parquet and prepares the current metadata for downstream indexing.

Keep derived outputs separate from authoritative database records. Use revision or input information to determine whether an output needs to be refreshed, and make sure an interrupted job can be restarted without publishing an incomplete snapshot.

**Completion criteria:**

- A successful export produces a readable Parquet snapshot with the expected schema and record counts.
- Exported records match the corresponding declared source state.
- An interrupted export does not replace a previously valid snapshot with a partial one.
- Repeating the workflow produces logically equivalent output for the same input.

### M5 — BM25 search and reviewer application

Implement the BM25 search index over paper titles and abstracts. Make sure important technical identifiers, model names, and hyphenated terms are handled reasonably by the tokenizer.

Build the FastAPI operations for search, paper information, screening projects, decisions, and export. Then build the Streamlit interface around those operations.

The initial UI should support entering a query, viewing ranked results, opening abstracts and original paper links, labeling papers, adding notes, reopening projects, and exporting screening results.

**Completion criteria:**

- A known paper can be found by searching for its title or distinctive technical terms.
- The UI displays the results in the order returned by the search backend.
- Screening decisions saved through the UI can be retrieved through the API and survive restarts.
- After importing an update and refreshing the index, the current metadata is searchable without losing previous labels.
- Exported results accurately reflect the saved screening decisions.

### M6 — Semantic search

Choose a small retrieval-oriented sentence embedding model that runs on a CPU. Implement document encoding, query encoding, vector storage, and similarity ranking.

Store the relevant model configuration and paper revision information with the embeddings so unchanged documents can reuse compatible vectors and changed documents are re-encoded when necessary.

Add a search-mode selector to the reviewer. BM25 should remain the default, and semantic search should return its own ranked list rather than combine the rankings automatically.

**Completion criteria:**

- The semantic index can be built and queried on a CPU.
- Natural-language topic queries retrieve sensible results on a controlled collection.
- The same paper can be screened regardless of the search mode used to find it.
- Changed text or incompatible model configuration invalidates affected embeddings.
- The application reports the actual indexed corpus and handles unavailable or incomplete indexes clearly.
- A small retrieval evaluation compares both methods using the same defined candidate collection and relevance judgments.

### M7 — Spark batch processing

Implement a local Spark job that reads an existing Parquet snapshot and an incoming batch, normalizes records as needed, deduplicates them, and produces a merged snapshot of the expected current paper records.

Use the processing policy from M1 instead of inventing different rules for Spark. Compare the batch results with the reference processor on controlled inputs.

Also prepare a comparison of equivalent CSV and Parquet inputs for the same batch workload.

**Completion criteria:**

- The merged snapshot contains the expected latest record for each paper.
- Duplicate, older, newer, and conflicting inputs are handled consistently with the documented rules.
- Reordering inputs or replaying the same batch does not change the intended logical result.
- CSV and Parquet experiments produce equivalent logical outputs before their runtimes and storage sizes are compared.
- The batch job writes its own output without changing the live application database.

### M8 — Evaluation and reproducible evidence

Prepare scripts and configurations for correctness tests, retrieval evaluation, and performance experiments. Record the actual data sizes, machine configuration, commands, results, and limitations.

Measure Kafka publication, MySQL persistence, index building, search latency, embedding generation, and Spark batch processing separately where appropriate.

Include controlled failure and replay tests so the evidence covers reliability as well as performance.

**Completion criteria:**

- Experiment inputs and configurations are recorded.
- Reported results can be traced to saved measurements or test outputs.
- Data size and search-index coverage are reported separately if they differ.
- No experiment is marked successful merely because a command exited without an error.

### M9 — Final verification and technical handoff

Review the complete repository, simplify unnecessary implementation details where possible, and verify the documented startup procedure from a clean checkout or isolated environment.

Prepare the README, architecture overview, runbook, evaluation summary, and a small demonstration workflow.

**Completion criteria:**

- A fresh environment can reproduce the small-data end-to-end demonstration.
- Real-service tests verify metadata correctness, replay, and persistent screening decisions.
- Both search modes and the Spark workflow can be demonstrated using the documented commands.
- Benchmark claims are supported by saved evidence, and incomplete larger-scale experiments are clearly identified.
- The repository retains the required development history and accurate records of AI assistance.

## User

Why are we doing MySQL before Kafka? In the actual architecture, the data first goes into Kafka and then MySQL. Wouldn't it make more sense to implement Kafka first?

## ChatGPT

The implementation order does not have to follow the data flow exactly.

The consumer depends on the metadata processing and database logic being correct. If we implement both the Kafka consumer and database revision handling at the same time, it will be harder to determine whether an incorrect result is caused by Kafka, parsing, or the database transaction.

By implementing M1 and M2 first, we can verify the expected behavior directly with a controlled set of records. M3 can then focus on how those same records are delivered, acknowledged, and replayed through Kafka.

The final ingestion path will still go through Kafka. Direct database operations during development are useful for testing individual components, not a replacement for the intended production workflow.

## User

For the fixture dataset, how should we design it? Should we just take the first 1000 papers from the arxiv dataset and work with that?

## ChatGPT

I would use two kinds of small datasets.

The first would be a deliberately constructed correctness fixture. It can be very small, because its purpose is to exercise known edge cases rather than represent the full arXiv collection. For example, include a paper's first revision, an identical copy, a newer revision, and an older revision arriving afterward. Include a conflicting payload and a malformed input as separate cases. Specify the expected final records and revision behavior in advance.

The second would be a sample of real research paper metadata, including enough papers on several related and unrelated topics to check retrieval behavior. It could start at approximately 1,000 records.

A random or consecutive sample from arXiv may not contain enough relevant papers for a query about a narrow topic such as VLM KV cache. That would make it difficult to distinguish poor search quality from a lack of relevant papers in the indexed collection.

The correctness fixture should remain small and reproducible even after the project starts working with larger real datasets.

## User

How should we organize the testing? Do we need to create tests for every function as we are developing the project?

## ChatGPT

We should prioritize tests based on what would cause incorrect or lost data, rather than try to test every function simply to increase coverage.

Unit tests are useful for normalization, identifier handling, revision comparison, validation, and other logic that does not require running services. Integration tests should verify transactions and persistence using real MySQL, as well as message delivery, recovery, and replay using real Kafka.

We should also have an end-to-end test that imports a fixture, builds the search indexes, saves a screening decision through the API, processes an update, refreshes the indexes, and verifies that the decision is still available.

Spark needs its own correctness tests using controlled input and expected output. Search needs retrieval tests using meaningful queries and relevance judgments, not just a check that a list of results was returned.

The tests should be added alongside the relevant milestone. Waiting until M9 to test all of these behaviors would make debugging much more difficult.

## User

For BM25 and semantic search, I am a little concerned about how we are going to evaluate whether the returned papers are actually relevant to the search query. How should we approach that?

## ChatGPT

Start by separating functional verification from retrieval evaluation.

For functional verification, we can use queries with known expected papers and ensure the index contains those papers. Exact-title and technical-name queries are particularly useful for checking BM25, while natural-language descriptions are useful for checking semantic search.

For retrieval evaluation, define a fixed candidate collection and a set of queries with relevance judgments. Ideally, include both queries containing exact terminology and queries describing a research problem in more general language.

Recall@50 can be useful for a screening application because missing relevant papers is costly. We could also report a ranking metric such as MRR or precision at a smaller cutoff, depending on the available labels.

We should compare the two methods on the same candidate collection. If semantic search only covers a subset of the metadata, we must report that coverage rather than treat papers missing from the semantic index as evidence of inferior ranking alone.

For the initial version, there is no need to build an automated system that decides whether every returned paper is relevant. That would introduce a separate problem that is outside the project's core scope.

## User

At what point should we start working with the larger dataset? I would like to eventually be able to work with at least 100,000 papers, and possibly all of arxiv if my computer can handle it.

## ChatGPT

I would establish the full workflow on the fixture first, then increase the real-data corpus gradually. The larger experiments can be prepared during M8 and expanded once the small-data workflow has passed the relevant checks.

| Dataset stage | Main purpose |
| --- | --- |
| Small correctness fixture | Verify expected state and recovery behavior |
| Approximately 1,000 papers | Develop and demonstrate the end-to-end application |
| 10,000 papers | Identify early scaling and indexing issues |
| 50,000 papers | Evaluate resource growth and longer processing runs |
| 100,000 papers | Target larger-scale experiment |
| Full pinned arXiv metadata snapshot | Optional expansion, subject to resource limits |

At each stage, verify record counts and revision behavior, check the indexing coverage, and record processing time, memory usage, storage growth, remaining disk space, and backlog. Move on only when the previous stage is stable enough to justify the next run.

Semantic embedding generation may become the main bottleneck, especially on a CPU. We can report separately how many papers were ingested, how many are searchable through BM25, and how many have valid semantic embeddings.

A successful 100,000-paper experiment is not the same as establishing that the full dataset can be processed. I would avoid assuming the full snapshot is feasible until we have measurements from smaller runs.

## User

For the progress of the project, can we have something in the repository that keeps track of which milestones have been completed? I think that would be helpful since there are a lot of different components.

## ChatGPT

Yes. I would use a single `PROGRESS.md` file for that purpose, with an entry for every milestone.

Each entry can include the following:

- Current status: not started, in progress, blocked, or completed.
- Main files and functionality delivered.
- Commands actually executed and their observed results.
- Paths to test outputs, reports, or other evidence.
- Remaining limitations or blockers, who is addressing them, and the next action.
- A short explanation of the implemented component that you could use during the project walkthrough.

It is important that completion is based on verification rather than just the presence of code. For example, M3 should not be marked complete simply because the producer and consumer files exist. It should have evidence that a real import and replay produced the expected result.

We should also keep implementation status separate from large-data experiment status. The small-data project could be fully functional even if a longer 100,000-paper experiment has not been completed yet.

## User

Should we make git commits after every milestone? The professor specifically mentioned that she wants the git repository to show the commit history.

## ChatGPT

I would commit meaningful changes as development progresses, especially after a component becomes functional and passes its relevant checks. Some milestones may require several commits, while others may only require one or two.

For example, schema changes, ingestion logic, search functionality, and integration tests can each have their own focused commits when that reflects how the work was actually done.

The commit messages should explain what changed rather than just say `update code`. Avoid committing credentials, generated indexes, full arXiv datasets, database volumes, or other large local artifacts. Keep the small fixtures and reproducible experiment scripts in Git.

Also retain the real AI conversations and identify AI-generated code as required by the professor. The repository history and AI records should accurately reflect the development process.

## User

Once we complete M9, would we consider the project to be done? I don't want to keep adding new features if they are not necessary for the project.

## ChatGPT

Yes. M9 should be the final implementation milestone for the agreed scope.

I would consider the system ready for technical review when someone can follow the README in a fresh environment, run the offline fixture through Kafka and MySQL, use BM25 and semantic search, save and recover screening decisions, and run the Spark batch workflow. The correctness and recovery tests should pass, and any performance or retrieval claims should be traceable to real evidence.

The 100,000-paper experiment is a separate evaluation target. If a larger experiment remains incomplete, we should report its status rather than add more features or claim a scale that has not been verified.

Features such as full-text retrieval, hybrid search, automatic relevance classification, multi-user collaboration, and cloud deployment are not required to complete the current version.

## User

That sounds good. I think we should follow this plan and focus on getting the core functionality working first. We can start with M0 and then work on each milestone in order. If there are any issues with the previous milestone, we should fix them before moving on to the next one.

## ChatGPT

That approach keeps the implementation manageable. Start with the environment and real-service smoke tests in M0. Then establish the paper-processing rules and fixture expectations in M1 before adding persistence and ingestion.

For every milestone, review the implementation against its acceptance criteria, run the relevant checks, save the results, and update the progress record. If a test exposes a problem in an earlier component, resolve that problem before building additional functionality on top of it.

The immediate goal is a verified small-data system. Scaling, optimization, and final evaluation should build on that foundation rather than replace it.
