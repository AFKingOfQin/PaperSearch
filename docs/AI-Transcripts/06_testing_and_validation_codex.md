# PaperSearch — Testing and Validation

## User

Following the code review, I want to have a more systematic set of tests for the project. Please help me plan and generate the tests for the program in `E:\PaperSearch`. I want to make sure all of the core functions work as expected, especially when the different parts of the program work together. I don't want to add a lot of tests for things that are not really relevant to the project.

## Codex

I would organize the tests around the actual responsibilities of PaperSearch rather than try to maximize test coverage for every individual function.

The previous review established a useful starting point: the clean export of commit `93a6ac1` had 17 passing tests, Ruff passed, and the Docker Compose configuration was valid. The Docker-backed integration checks were still blocked, and the full reviewer and Spark workflows had not been verified.

I would divide the remaining work into four groups:

1. Regression tests for the issues identified in the previous review.
2. Integration tests for Kafka ingestion, MySQL transactions, index refresh, and screening persistence.
3. An end-to-end test of the research paper search and screening workflow, plus a separate Spark batch test.
4. Evaluation scripts for retrieval quality and data processing performance.

Before adding anything to the repository, I would inspect the existing tests and commands so we can reuse them. These are the initial inspection commands I would use from PowerShell:

```powershell
Set-Location E:\PaperSearch
git status --short
git rev-parse HEAD
git ls-files tests
python -m pytest --collect-only -q
python -m pytest -q
python -m ruff check .
docker compose config --quiet
```

The collected tests would tell us which cases are already covered. I would not duplicate an existing test unless it only verifies part of the expected behavior.

## User

For the tests that passed during the previous review, do we need to generate new tests for those issues as well?

## Codex

Not necessarily. If the existing regression tests already reproduce the original failures and verify the fixes, keep them.

These are the cases I would look for:

| Regression | Required assertion |
| --- | --- |
| Equal-version revision conflict | If the winning payload changes the current revision, its embedding work is created exactly once. |
| Replay of the winning revision | No duplicate revision or embedding work is created. |
| Invalid lexical bootstrap artifact | A different SQLite file of the same size is rejected before the database is modified. |
| Semantic model unavailable | The response explicitly reports BM25 as the effective mode and returns the same ranked IDs as a direct BM25 request with equivalent settings. |
| Destructive project deletion | Canceling leaves the project and its screening history intact; confirming performs the intended deletion. |

The first four findings from the code review included the repository-completeness issue as well as the first three functional fixes. The deletion issue was still open in the reviewed commit. I would check the current state before deciding whether its test can be expected to pass.

For repository completeness, I would retain a clean-checkout verification step rather than add a Python unit test that inspects the Git history.

## User

How should we design the small dataset for testing? I feel like using a random subset of the arxiv dataset wouldn't really let us test all the cases we want to test.

## Codex

A deterministic fixture would be better for correctness testing. We should know the expected final state before running the program.

For example, we could create a small synthetic dataset with three distinct paper IDs. The records would resemble the project's normal arXiv metadata inputs, but the values would be deliberately selected to exercise the update logic.

| Input | Paper ID | Version | Purpose |
| --- | --- | --- | --- |
| A | 2601.00001 | 1 | Initial record |
| B | 2601.00002 | 1 | Initial record |
| C | 2601.00003 | 1 | Initial record |
| A again | 2601.00001 | 1 | Exact duplicate |
| D | 2601.00001 | 2 | Newer revision |
| A again | 2601.00001 | 1 | Older revision arriving after a newer revision |
| E | 2601.00002 | 1 | Different payload with the same version and timestamp as B |
| E again | 2601.00002 | 1 | Replay of a conflicting payload |

The equal-version conflict should use the actual project's documented conflict policy. Once we inspect that policy, we can choose the payloads and calculate the expected winner independently of the implementation being tested.

At the end, there should be exactly three canonical paper records. Paper `2601.00001` should point to version 2, paper `2601.00002` should point to the expected conflict winner, and paper `2601.00003` should remain unchanged.

We should also verify the revision and embedding queue state according to the policy, not just the canonical paper count. Three correct IDs do not prove that replay was idempotent.

I would split the fixture into an initial batch and an update batch so we can save screening decisions before ingesting the changes.

## User

Can we just use this one fixture to test Kafka, MySQL, and Spark? I want to avoid having a lot of different datasets for the tests.

## Codex

Yes. I would reuse the same logical records for the live ingestion and Spark batch tests. We can convert them into the formats required by the existing entry points without changing their meaning.

The initial batch provides a known starting state. The update batch introduces an exact duplicate, a newer version, an older version, and a conflict. An expected-results fixture can describe the correct final canonical metadata.

The two workflows should be verified independently against that expected result. If we only compare the output from Spark with the output from MySQL, both implementations could make the same mistake and the test would still pass.

For search quality testing, I would use a separate collection of actual paper metadata and relevance judgments. A synthetic fixture is good for testing identity, ordering, and persistence, but too small and artificial to establish that the search rankings are useful on real research topics.

## User

For Kafka, please generate tests that check both resume and replay. Also make sure that when a record is published to Kafka it actually gets added to the database.

## Codex

I would use the real Docker-backed Kafka and MySQL services for these tests. Mocked clients are useful for testing the checkpoint calculation, but they cannot establish that the broker and database interact correctly.

The producer resume test should follow this sequence:

1. Start an isolated test environment and prepare the initial fixture.
2. Begin ingestion and stop the producer after a bounded publication window has been acknowledged.
3. Verify that the saved checkpoint reflects the acknowledged input position, not merely the last line that was read.
4. Restart the producer using the same archived input and allow ingestion to finish.
5. Wait until the consumer has committed the expected records to MySQL, then assert the complete canonical state.

The replay test should deliberately read the archived fixture again, rather than resume at its completed checkpoint. Before replay, capture the canonical records, revision identities, and embedding work state. After replay, verify that the logical state is unchanged.

A test should also exercise the case where Kafka has acknowledged a window but the producer stops before persisting the checkpoint. Re-publication is acceptable in that case. Creating duplicate accepted revisions is not.

For waiting on asynchronous work, I would use a bounded poll against the expected database state rather than a fixed `sleep(10)`. A fixed delay might pass on one computer and fail on another even though the implementation is correct.

The polling code should time out with a useful error showing which records or revisions were still missing.

## User

Would stopping the producer in the middle of ingestion also test the Kafka consumer recovery? Or are those two separate tests?

## Codex

They are separate failure cases.

Producer recovery checks how the input file and the publication checkpoint are handled. Consumer recovery checks how Kafka offsets and database commits are handled.

For the consumer, I would test two important failure windows:

- Before the MySQL transaction commits: the record should remain eligible for processing after the consumer restarts.
- After the MySQL transaction commits but before the Kafka offset commits: the message may be delivered again, but its database effects should not be duplicated.

We should also verify that a later record in a partition does not cause an offset to be committed past an earlier failed record in that partition.

Where possible, the failure injection should use existing transaction or offset-commit boundaries and a test-controlled signal. Randomly terminating a consumer process would demonstrate restart behavior, but it would not guarantee that we exercised the specific failure window we intended to test.

This is a test of recovery from processing interruptions with durable local services. It is not a demonstration that a single Kafka broker can survive permanent loss of its storage volume.

## User

I already have a large amount of paper data on my computer. Please make sure that none of the integration tests change the existing database or remove the data. I don't want to rebuild the embeddings again.

## Codex

I would run the integration tests against a completely isolated Compose project, with separate MySQL and Kafka volumes, a separate artifact directory, and separate host ports if the normal services are running at the same time.

A different Compose project name by itself is not sufficient if the configuration uses explicit shared volume names, external networks, absolute bind mounts, or fixed container names. We need to inspect the resolved configuration and ensure that the test services cannot accidentally reference the live data.

I would keep the tests opt-in when they require Docker. The regular unit-test command should not start services or modify existing application data.

The test runner should print the resolved test database and artifact locations before starting any writes. Cleanup should be limited to resources created specifically for the test run. I would not run a volume-removal command against the normal PaperSearch Compose project.

For the unit tests that simulate a missing semantic model or an invalid lexical index, use temporary paths or injected dependencies. Do not rename, replace, or delete the real model files and published indexes.

If isolated infrastructure cannot be started, the integration tests should be marked blocked or skipped with a clear reason. They should not quietly switch to the normal local database.

## User

For the semantic search tests, do we need to use the actual embedding model? I feel like generating embeddings every time we run the tests would be a waste of time.

## Codex

I would separate the tests into two levels.

For the fast regression tests, use a small deterministic substitute encoder. We can give it known document and query vectors and verify that the search code ranks them correctly, associates them with the correct paper IDs, handles missing or stale revisions, and reports fallback behavior correctly.

For example, if the implementation uses cosine similarity, a simple test could use these already-normalized vectors:

```python
query = [1.0, 0.0]

vectors = {
    "paper_a": [1.0, 0.0],
    "paper_b": [0.6, 0.8],
    "paper_c": [0.0, 1.0],
}

expected_order = ["paper_a", "paper_b", "paper_c"]
```

The actual test should feed these vectors through the existing search implementation and assert the returned IDs. This example is a test input, not a replacement implementation of the ranking code.

For a separate model-backed integration test, use the configured sentence embedding model on a small number of real paper titles and abstracts. Verify that document and query encoding use compatible settings, that the generated vectors are valid, that the loaded artifacts match the model configuration, and that a few well-defined search queries return plausible results.

The model-backed check can run less frequently than the fast tests. If the model is not available locally and downloading is not permitted, report the check as skipped or blocked instead of claiming that the real semantic retrieval path passed.

## User

How would we test that the correct version of a paper is returned after a revision? I think this is especially important for semantic search since the paper might have the old embedding.

## Codex

I would include a revision-refresh integration test that deliberately changes a paper's searchable text.

The first version could contain a unique phrase such as `fixture alpha mechanism`. The updated version could replace that phrase with `fixture beta mechanism`. After the initial index build, save the paper's current revision ID and the index's associated revision information.

Then ingest the updated version through the normal Kafka path. Check that MySQL selects the expected current revision and that the corresponding embedding work is recorded.

Before refresh, check the application's actual documented behavior for stale or pending search data. It should not present a vector from the previous revision as if that vector represents the new text.

After refreshing the indexes, verify that the lexical index contains the updated text and that the semantic index references the new accepted revision with compatible embedding data. The result should still refer to the same stable paper ID.

For the lexical test, a unique fixture term makes it easy to verify that the new text is indexed and the old text is not. For semantic search, revision identity and input-text compatibility are stronger assertions than expecting the new phrase to rank first for every possible query.

Replaying the update should not introduce duplicate search entries or redundant embedding work.

## User

Can you also test the part where the program returns BM25 results if semantic search doesn't work? I want to make sure it still returns relevant papers instead of just returning an empty list.

## Codex

The fallback regression should compare the output of a semantic request with a direct BM25 request for the same query and filters.

I would generate cases for:

- Semantic model or index initialization fails while the lexical index is available.
- Semantic search is available and executes normally.
- Semantic search executes successfully but returns no results.
- Neither search mode can be initialized.

In the first case, assert that the requested mode remains semantic, the effective mode is BM25, a fallback reason is present, and the returned ordered paper IDs match direct BM25 results. This verifies that the fallback executes the real lexical retrieval path.

In the second and third cases, the program should not fall back just because the semantic ranking differs from BM25 or contains no results.

If neither mode is usable, the API should return an appropriate error rather than pretend that the search succeeded. The reviewer should display that condition clearly.

For the reviewer itself, I would also check that switching the effective mode resets pagination and that the displayed mode and explanation agree with the API response.

## User

For the screening part, can we test the whole workflow from the user opening the project to labeling the papers and then closing the program? I want to make sure the user doesn't lose anything when they reopen it.

## Codex

Yes. I would use a single end-to-end screening scenario with the deterministic fixture:

1. Start the isolated infrastructure, ingest the initial batch, and build the search indexes.
2. Create two screening projects through the API.
3. Search for one of the fixture papers in the first project and save a relevant label with a note.
4. Save a different label for the same paper in the second project.
5. Restart the API and reviewer processes while preserving the isolated database volume.
6. Reopen both projects and verify that their independent labels and notes are still present.
7. Ingest the update batch and refresh both indexes.
8. Search for the updated paper and verify that its existing screening decisions are still associated with its stable ID.
9. Export the screening results and compare them with the expected project-specific decisions.

If screening history is part of the supported schema, also change a decision and verify that the latest decision is displayed while the expected prior event remains recorded.

Most of this can be tested through the API without automating a browser. That provides a reproducible check of the backend and its persistence behavior.

I would then perform a small manual Streamlit smoke test to confirm that searching, labeling, reopening a project, and downloading the export work from the actual interface. If the deletion confirmation has been implemented, include both the cancel and confirm actions in a disposable test project.

The API test and the UI smoke test should be reported separately. A passing API test does not prove that every Streamlit interaction works.

## User

For Spark, I don't think we need to test its performance for every possible dataset. I mainly want to prove that the Spark batch job produces the correct result. What would be the simplest way to do that?

## Codex

Use the same controlled initial and update records from the ingestion tests and run the existing local Spark merge entry point against temporary inputs and outputs.

Read the resulting Parquet snapshot and compare its logical rows with the independently defined expected canonical records. Verify the stable paper IDs, version information, and fields changed by the revisions.

The comparison should not depend on row order or the number of Parquet part files, unless those properties are explicitly part of the project's contract. Spark can produce equivalent logical datasets with different physical file layouts.

I would also check that the output contains exactly one current record per paper and that the original input files remain unchanged. If the merge can be rerun with the same records, verify that the logical output is deterministic.

The test should not write the merged snapshot back into the normal MySQL database. Spark has a separate batch responsibility in this project.

For a performance comparison between CSV and Parquet, if we retain that experiment, use equivalent input data and the same logical transformation. First verify that the outputs agree; then record runtime and storage size. We do not need a separate performance test for every correctness case.

## User

What about testing the actual relevance of the returned papers? For example, I want to know if the search works well for something like VLM KV Cache, but I don't want the program to only perform well on that specific topic.

## Codex

I would create a small retrieval evaluation set covering several query types and research areas.

| Query type | Example |
| --- | --- |
| Exact title or method | `LOOK-M` |
| Hyphenated technical identifier | `VL-Cache` |
| Technical topic | `VLM KV Cache` |
| Descriptive query | `reducing memory usage during multimodal language model inference` |
| Unrelated research area | `graph neural networks for molecular property prediction` |
| Another descriptive query | `detecting distribution shifts in time series forecasting` |

These are candidate queries, not predetermined relevance judgments. We need to review the actual corpus and identify which papers are relevant to each information need. For exact-title queries, we should verify that the expected paper is present before measuring its rank.

Both retrieval methods should be evaluated over the same declared candidate set when comparing ranking quality. The previous review reported that lexical and semantic index coverage differed substantially. Comparing them across different candidate collections without accounting for that difference would not isolate ranking quality.

I would report Recall@10, Recall@50, and MRR for appropriate queries. Recall measures the fraction of known relevant papers retrieved within the selected cutoff. MRR measures how early the first judged-relevant paper appears.

If the evaluation labels are incomplete, state that limitation. We cannot claim that an unjudged paper is irrelevant simply because it is absent from the list of known relevant papers. We also cannot use the results to claim complete coverage of every relevant paper on arXiv.

## User

Should we define a minimum recall that both methods need to achieve before considering the tests passed?

## Codex

I would not set an arbitrary threshold before examining the evaluation data and the baseline results.

There are deterministic retrieval checks that should pass as ordinary regression tests: a known exact-title paper should be retrievable under the intended lexical behavior, the vector ranking should match the expected order on controlled inputs, and query results should contain the correct paper IDs and revisions.

Real-world retrieval evaluation is different. Its results depend on corpus coverage, relevance labels, query wording, and the selected embedding model. We should establish a baseline, report the actual metrics, and investigate poor results. If we later change tokenization or the embedding model, we can compare against the same evaluation set to see whether the change helps or hurts.

I would avoid tuning the search rules specifically to improve `LOOK-M` or `VL-Cache`. Those queries are useful regression examples, but any ranking improvements should also be evaluated on other topics.

## User

We have a lot of papers in the full dataset. For the performance tests, do we need to import everything again just to record the results? I would prefer to avoid doing that if possible.

## Codex

No. We can keep the existing large-data artifacts and measure workloads against them where appropriate. For example, search latency and index coverage can be measured using a verified existing index without rebuilding the entire corpus.

For ingestion throughput, we need actual ingestion measurements. If earlier runs produced reliable logs with the corpus identity, configuration, and start and end conditions, those measurements can be reused. Otherwise, run controlled imports at manageable sizes in the isolated test environment.

I would record the following separately:

- Kafka publication throughput and the time when publication is acknowledged.
- Time when the expected records are durably committed in MySQL.
- Time when the corresponding accepted revisions become visible in each search mode.
- Consumer backlog, peak memory use, disk growth, and final record counts.
- BM25 index build time, semantic encoding time, and coverage for each index.
- Search latency for a fixed query workload, with cold and warm conditions identified.

The 1,000-, 10,000-, 50,000-, and 100,000-record stages can be used as expansion targets. I would only proceed to a larger ingestion run when the previous run completes with correct counts, acceptable resource usage, and sufficient disk space.

Do not combine the time from an existing full-size index with the time from a small ingestion run and present it as one full-corpus end-to-end measurement. Report the actual size and configuration of each experiment.

## User

How should we organize the tests? I don't want the test directory to become larger than the actual program.

## Codex

I would preserve the current test directory structure and add only the missing cases. A possible organization, if it fits the existing suite, would be:

```text
tests/
├── test_record_processing.py
├── test_bootstrap.py
├── test_search.py
├── test_screening.py
├── integration/
│   ├── test_ingest_recovery.py
│   ├── test_search_refresh.py
│   ├── test_screening_persistence.py
│   └── test_spark_merge.py
└── fixtures/
    ├── initial.jsonl
    ├── updates.jsonl
    └── expected_records.json
```

These are suggested file names, not a claim about the current repository layout. The existing files should be reused where possible instead of being renamed just to match the example.

For tests requiring external services or the real embedding model, we can register pytest markers such as `integration` and `model` if the project does not already have an equivalent convention.

A possible command split after those markers are implemented would be:

```powershell
# Fast tests without external services or model downloads
python -m pytest -q -m "not integration and not model"

# Integration tests after isolated test services are ready
python -m pytest -q -m "integration and not model"

# Tests requiring the configured real embedding model
python -m pytest -q -m model
```

Performance experiments and relevance evaluation can remain separate commands rather than ordinary pytest tests. Their outputs are measurements, not necessarily simple pass or fail assertions.

## User

Can you generate the tests based on the things we discussed? Please don't change the actual source code unless you find a bug and tell me about it first.

## Codex

The implementation should start by collecting the existing test suite and identifying the current entry points, database fixtures, API response schema, and Spark command. Then add tests against those interfaces rather than introducing parallel implementations of the application logic inside the test files.

For each new test, I would define the setup, action, and expected result explicitly. The expected result should come from the fixture or the documented behavior, not from invoking the function under test a second time to calculate what its answer should be.

I would keep changes limited to test files, small deterministic fixtures, and the test configuration needed to run the isolated integration environment. If a test exposes a source-code defect, report the failing assertion and the relevant code path before modifying production code.

I would also preserve the test distinction we discussed:

- Fast deterministic tests for logic and the existing regressions.
- Real-service integration tests for recovery, data persistence, and index refresh.
- A model-backed retrieval smoke test and a real reviewer smoke test.
- A local Spark output verification.
- Separate retrieval-quality and performance measurements.

Any integration command needs to run against explicitly confirmed test resources. If a required service or model cannot be used, the result should remain blocked or skipped. Merely generating the tests would not establish that they pass.

## User

After running the tests, what should the final results look like? I want to put the results in the project documentation and use some of them in my video.

## Codex

I would record the commit, environment, dataset identity, and commands used, followed by a short verification table. The table should distinguish newly executed checks from results inherited from the earlier review.

For example, the starting verification record from the previous review is:

| Check | Recorded status |
| --- | --- |
| Clean export of `93a6ac1` | Verified in previous review |
| Existing test suite | 17 passed in previous review |
| Ruff | Passed in previous review |
| Compose configuration validation | Passed in previous review |
| Four targeted code-review fixes | Verified in previous review |
| Producer resume and replay with real services | Requires runtime verification |
| Consumer transaction and offset recovery | Requires runtime verification |
| End-to-end screening persistence | Requires runtime verification |
| Spark merged snapshot correctness | Requires runtime verification |
| Real-model retrieval evaluation | Requires measurement |
| Large-data performance | Requires measurements or verified earlier logs |
| Project deletion confirmation | Open in the reviewed commit; recheck current source |

These are not new test execution results. The final documentation should replace the pending entries with actual outcomes, including failed assertions, skipped checks, or environmental blockers where applicable.

For the five-minute video, I would focus on a concise demonstration of the system rather than show every test. Show an initial search, save a screening decision, ingest a controlled update, and show that the updated paper is searchable without losing the decision. Briefly explain the recovery tests and the Spark batch result, then show one table of actual retrieval or processing measurements.

That will give a much clearer demonstration of the CS 544 concepts than scrolling through a large number of test files.

## User

I think that should be enough for testing the system. I still want to improve the quality of the paper search, especially for semantic search. Can we focus on that next?

## Codex

Yes. The testing plan separates the correctness of the pipeline from the usefulness of the search rankings. Once the regression and integration checks are in place, we can focus specifically on retrieval quality without unnecessarily redesigning the ingestion or screening components.

The next step would be to inspect the tokenizer, indexed document text, embedding model conventions, vector-to-paper mapping, index coverage, and the results of several representative queries. We can use the same evaluation set to compare the behavior before and after any search-related changes.

I would keep BM25 as the default, semantic search as a separate mode, and avoid hard-coding exceptions for individual paper titles or research topics.
