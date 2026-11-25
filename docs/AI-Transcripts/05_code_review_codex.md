# PaperSearch — Code Review

## User

The project is in `E:\PaperSearch`. Please review the project for any issues. Check if it aligns with all the expectations we had for the project. I also want to make sure there aren't any unnecessary parts in the code that are not related to the core functions.

For now, don't make any changes to the code. Just review the project and tell me what the problems are.

## Codex

I'll focus the review on the expected behavior of PaperSearch, rather than on adding more features. I'll use the findings from the earlier repository reviews for this walkthrough; this is not a new execution against your local checkout.

The review should cover:

- Repository completeness and reproducibility from a clean checkout.
- Kafka ingestion, replay, and consumer recovery.
- MySQL metadata revisions and persistent screening decisions.
- BM25 and semantic search, including index freshness and fallback behavior.
- FastAPI and Streamlit integration.
- The separate Parquet and Spark batch-processing workflow.

For the repository checks, these are the commands I would start with in PowerShell:

```powershell
Set-Location E:\PaperSearch
git status --short
git log -5 --oneline
git ls-files
python -m pytest -q
python -m ruff check .
docker compose config --quiet
```

Passing these checks would be useful, but would not replace the Docker-backed integration tests.

### Findings

The earlier review identified five issues.

**1. Required project files are missing from the committed version.**

The working tree contains changes that are not represented in `HEAD`, including `bootstrap.py`, two migration files, a bootstrap test, and modifications to existing tracked files. The current working directory may run correctly, but someone cloning the repository at the current commit would not receive the same program.

**2. The revision-conflict path can leave the semantic index behind the database.**

File: `src/papersearch/database.py`

When two different payloads share the same source version and timestamp, the database applies its conflict-resolution policy. If this changes the current revision without creating the corresponding embedding work item, the semantic index cannot catch up through its normal processing workflow.

**3. Bootstrap does not adequately validate the existing lexical index.**

File: `src/papersearch/bootstrap.py`

The bootstrap operation can accept an existing `lexical.sqlite` file without sufficiently establishing that it is the intended artifact. A different SQLite file, even one of the same size, should not be accepted as the expected index. This validation needs to happen before bootstrap changes the database.

**4. Semantic search has an incomplete fallback path.**

Files: `src/papersearch/api.py`, `src/papersearch/reviewer.py`

When the semantic search model or index cannot be loaded, requesting semantic search can fail instead of returning an explicitly identified BM25 fallback. This can make the reviewer less usable even though a working lexical index is available.

**5. Deleting a screening project can permanently remove screening history without confirmation.**

Files: `src/papersearch/reviewer.py`, `src/papersearch/api.py`

The deletion path removes a project together with its decisions and decision history. The interface exposes that destructive operation without a separate confirmation step.

### Verification

The earlier review recorded nine passing tests, a successful Ruff check, and successful Docker Compose configuration validation. Docker-backed integration checks were blocked, so those results did not establish recovery behavior with a running Kafka broker and MySQL database.

The overall architecture is consistent with the expected scope. The main issues concern correctness at the boundaries between components and reproducibility, not missing technologies. I would address those before adding more features.

## User

Please explain more for each issue. How would they actually affect the program when using it?

## Codex

### 1. Committed files versus working-tree files

This is primarily a reproducibility issue. Your local directory may contain everything needed to start the program, but Git only records the files included in a commit.

For example, if the new bootstrap procedure depends on a migration that is present locally but absent from `HEAD`, a clean checkout may fail when initializing the database.

The appropriate validation is a clean export of the intended commit, not simply another run from the same working directory.

### 2. Revision updates and embedding generation

Consider the following input sequence:

```text
Record A: paper X, source version 2, timestamp T, payload A
Record B: paper X, source version 2, timestamp T, payload B
```

The two records are not identical. Suppose the conflict policy chooses B as the current revision.

If B becomes current in MySQL but the embedding queue only contains work for A, semantic search may still be ranking the previous text. Depending on how the index validates its revisions, paper X could instead become unavailable in semantic search until its current embedding is generated.

The required invariant is that whenever the accepted current searchable revision changes, the corresponding embedding work is recorded durably. Replaying either record must not create duplicate work.

### 3. Bootstrap validation

Suppose the user has downloaded or generated a published lexical index and places it in the expected location. The filename is correct, but the actual contents belong to another corpus or another index generation.

The bootstrap command should reject that file before changing the live database. Otherwise, the system can be initialized with metadata and a search index that do not describe the same collection.

Checking only the filename or size is insufficient. The artifact needs to be verified against trusted expected integrity information and the relevant index metadata.

### 4. Semantic fallback

The lexical index and semantic index do not necessarily have the same dependencies. For example, semantic search requires a compatible embedding model, which may not be available in a new local environment.

If a semantic request fails while BM25 is still usable, returning an explicit lexical fallback would allow the reviewer to continue working. The important distinction is that the program must tell the user which mode actually produced the results.

A valid semantic query that returns no results is not the same as a failure to execute semantic search. It should not automatically trigger fallback.

### 5. Project deletion

This does not affect the normal search ranking, but it affects the research workflow. If a researcher has screened hundreds of papers, an accidental click on Delete could remove all of that project's labels and notes.

A confirmation step can address the accidental-deletion problem without introducing another database table or a complete soft-delete system.

## User

The first issue can be fixed if I commit the new changes right?

## Codex

Yes, assuming that the missing files and modifications are all intentional and complete.

First inspect the untracked and modified files:

```powershell
git status --short
git diff
git diff --cached
```

Stage the required source files, migrations, tests, and related configuration. Avoid staging generated indexes, large datasets, credentials, database volumes, or unrelated local files.

After committing, verify that the expected files are included in `HEAD`:

```powershell
git ls-tree -r --name-only HEAD
```

I would then run the tests from a clean Git export of that commit. If they pass there, it is stronger evidence that the repository is self-contained than running them again in the original working directory.

## User

For the second issue, what exactly needs to change? Please try to keep the fix relatively simple. I don't want to add another complicated system just to fix it.

## Codex

The fix should stay in the existing database and embedding-queue workflow.

In `src/papersearch/database.py`, trace both the ordinary newer-revision path and the equal-version conflict path. Both paths need to enforce the same rule: if the accepted current revision changes, ensure that the corresponding embedding work exists.

Conceptually:

```text
Begin transaction
    Identify the existing paper and incoming revision
    Resolve whether the incoming revision becomes current
    If the current revision changes:
        Update the current revision reference
        Ensure embedding work exists for that revision
Commit transaction
```

The revision update and queue insertion should be part of the same transaction. The existing uniqueness or idempotency mechanism should prevent duplicate work when records are replayed.

I would add regression cases for:

- A new paper receiving its initial embedding work item.
- A normal newer revision becoming current.
- A different payload winning an equal-version conflict.
- Replaying the winning payload without creating another work item.
- An older or losing revision not changing the current paper.

There is no need for another worker service, message broker, or index type to fix this issue.

## User

For issue 3, can we just check the hash of the index file? I don't think we need to do anything more complicated than that.

## Codex

A content hash is a good starting point when the bootstrap process expects a specific published artifact.

The expected hash must come from the trusted manifest or other expected-artifact information, not from a value generated from the candidate file and then compared with itself.

I would keep the validation in `src/papersearch/bootstrap.py` and run it before any database initialization that modifies persistent data.

The regression test should include a valid SQLite file that has the same size as the intended index but different contents. It should be rejected, and the database should remain unchanged. A valid expected artifact should still be accepted.

Where the existing bootstrap workflow already checks the corpus and index metadata, keep those checks. There is no need to introduce a separate artifact management service.

## User

For issue 4, I want BM25 to be the default search method. If the user selects semantic search but the model doesn't work, can we simply return BM25 results and tell the user why?

## Codex

Yes. That matches the existing project scope.

I would make the change in the search API and the reviewer interface rather than duplicating search logic in Streamlit.

The API should distinguish the requested mode from the mode that actually generated the ranking. Conceptually, the response would contain information such as:

```json
{
  "requested_mode": "semantic",
  "effective_mode": "bm25",
  "fallback_reason": "Semantic model unavailable"
}
```

Those are illustrative response fields; use the existing response schema and naming conventions where possible.

The BM25 fallback should preserve the original query and applicable filters. The reviewer should display the effective mode and the reason for the fallback. If the displayed ranking changes modes, it should also reset pagination.

The most useful regression test is to make the semantic model unavailable, request semantic search, and compare the returned paper IDs and order with a direct BM25 request under equivalent settings. That checks whether the fallback actually works, rather than merely checking that the response does not contain an exception.

## User

For the fifth issue, do we really need to change the database? I think just asking the user if they are sure before deleting is enough for this project.

## Codex

A UI confirmation is sufficient for the accidental-click risk in the local reviewer, provided that the permanent deletion behavior is intentional and clearly documented.

I would leave the existing deletion API and database relationships in place. The reviewer can show a confirmation state that identifies the project and warns that its screening decisions and history will be permanently deleted.

Canceling should leave the data unchanged. Confirming should issue the delete request once and update the interface only after the operation succeeds.

This avoids introducing soft deletes, undo history, authentication, or additional administrative features that are outside the original scope.

## User

I have fixed the issues, please check again. Make sure you check if the actual fixes work, not just whether the code has been changed.

## Codex

The recorded follow-up review was performed against commit `93a6ac1`. It confirmed that the first four findings were addressed. The fifth remained open.

| Original issue | Follow-up result |
| --- | --- |
| Required files missing from `HEAD` | Fixed; the clean Git export contained the required changes. |
| Conflict winner not queued for embedding | Fixed; the winning revision was queued exactly once. Replaying it did not create additional work. |
| Insufficient lexical index validation | Fixed; a different SQLite artifact of the same size was rejected before database changes. |
| Missing semantic fallback | Fixed; the missing-model case returned the same results as direct BM25, and the reviewer handled the fallback and pagination reset. |
| Unconfirmed destructive project deletion | Still open in the reviewed commit. |

### Checks reported in the follow-up

- Clean Git export: tested.
- Test suite: 17 tests passed.
- Ruff: passed.
- Docker Compose configuration: passed.

The Docker-backed MySQL and Kafka integration checks remained blocked. The running Streamlit workflow and Spark batch parity were also not established by that review.

These distinctions matter: the recorded regression tests provide evidence that the four targeted fixes work in the tested conditions, but they do not establish that every runtime scenario has passed.

### Remaining finding

`src/papersearch/reviewer.py` still exposes the destructive project-deletion operation without the intended confirmation step. The associated API deletion behavior removes the project's decisions and history. If permanent deletion is intentional, this is mainly a reviewer interaction issue rather than a reason to redesign database storage.

## User

Other than the deletion issue, does the program align with all of our original expectations? Is there anything unnecessary in the code that we should remove?

## Codex

The reviewed design aligns with the main responsibilities we defined:

- Kafka handles normal ingestion and replay.
- MySQL maintains canonical paper metadata and screening history.
- BM25 and semantic search use derived retrieval artifacts.
- FastAPI provides the application boundary, and Streamlit provides the reviewer.
- Parquet and Spark support a separate batch workload.

I would not remove revision tracking, checkpointing, or index compatibility validation simply because they make the code longer. Those are necessary for the behaviors the project promises.

The candidates for simplification are duplicate normalization logic, unused alternative ingestion or search paths, unnecessary configuration options, and wrappers that do not provide a clear responsibility. I would identify them with actual call sites and tests before removing them; I cannot establish which specific helpers are unused without inspecting the current source.

There is also a difference between lexical and semantic index coverage. The earlier artifacts contained about 3.05 million lexical records and 486,123 semantic vectors. The program should report those separately rather than imply that every paper is available through both modes.

I would consider the four verified fixes complete for the tested cases. I would not consider the entire end-to-end project verified until the runtime checks are completed.

## User

What should we test next? I mainly want to make sure the whole program works together as expected. I don't want to just keep adding more unit tests that check individual functions.

## Codex

The next priority should be a fixture-based integration test of the complete workflow.

Use a small dataset with known stable paper IDs, duplicates, an older revision, a newer revision, and an equal-version conflict. Start the local infrastructure, ingest the records, and compare the resulting MySQL state with a predetermined expected result.

Then interrupt processing and resume it, replay the input, and verify that neither canonical paper counts nor embedding work counts increase incorrectly. Refresh the indexes and test that the accepted current revisions are searchable.

The reviewer test should create a screening project, search for papers, save decisions and notes, ingest a paper revision, and verify that the saved decisions remain available after a restart and an index refresh. The Spark test should use equivalent controlled inputs and compare its merged output with the expected canonical records.

Keep search quality evaluation separate from pipeline correctness. For BM25 and semantic retrieval, use a set of exact-title, technical-term, and descriptive queries over a common candidate collection rather than hard-coding special behavior for `LOOK-M`, `VL-Cache`, or `VLM KV Cache`.

I would keep the existing architecture and use these integration and regression checks to determine whether further changes are actually needed.
