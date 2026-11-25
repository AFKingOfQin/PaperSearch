# PaperSearch — System Architecture

## User

Now that we have defined the scope of the project, let's start planning the architecture. Can you give me an overall idea of how all the different parts of the program should work together? I want to keep the architecture relatively simple while still making good use of the things we learned in CS544.

## ChatGPT

I would separate PaperSearch into three main workflows: paper ingestion, search and screening, and batch processing.

The ingestion workflow is responsible for bringing paper metadata into the system and maintaining the current version of each paper. The search and screening workflow allows the user to work with that collection. The batch workflow processes archived records independently of the interactive application.

Here is a possible architecture:

```text
Offline fixture / arXiv JSONL
              |
              v
       Ingestion producer -----> Archived input batches
              |
              v
            Kafka
              |
              v
       Metadata consumer
              |
              v
            MySQL <--------> FastAPI <--------> Streamlit
              |                  |
              |                  v
              |           BM25 / semantic indexes
              |                  ^
              +---- Index refresh+

Archived records / Parquet snapshots
              |
              v
        Local Spark job
              |
              v
       Merged Parquet snapshot
```

MySQL would own the current paper metadata and screening decisions. Kafka would be the normal path for ingestion. The search indexes would be derived from the stored metadata, and Spark would operate on explicit batch inputs and outputs rather than becoming another independent writer to the live database.

## User

Why do we need both MySQL and Parquet? Wouldn't the two basically be storing the same data?

## ChatGPT

Some of the information will overlap, but they serve different workloads.

MySQL is appropriate for operations that need to access or modify individual records. For example, when a user marks a paper as relevant, the application needs to save that decision immediately. When a new version of a paper arrives, the consumer needs to determine whether the stored record should change.

Parquet is more suitable for processing large groups of records together. Spark can efficiently read selected columns, compare snapshots, deduplicate records, and write a new batch output.

I would treat MySQL as the source of truth for the live application and Parquet as storage for offline processing and reproducible experiments. The application should not need to query Parquet every time a user searches for a paper.

## User

For Kafka, how should we organize the data that we are publishing? Should we publish a whole batch of papers as one message or each paper as one message?

## ChatGPT

I would publish one paper record per message, using the stable paper identifier as the message key. The producer can still send records in bounded groups to improve throughput.

Each message should contain enough information for the consumer to process it independently. This includes the paper identifier, title, abstract, authors, categories, available publication and update timestamps, and source version information.

Using the paper identifier as the Kafka key ensures that records for the same paper are assigned to the same partition under a fixed partition configuration. That helps preserve their publication order within the partition. However, the consumer should still check the source version and timestamps because records from different imports or replays may arrive out of chronological order.

For the local project, one broker is sufficient. We do not need a multi-broker deployment to demonstrate the main ingestion and recovery concepts.

## User

If I am importing a large arxiv dataset and stop the program in the middle of the import, do I have to start from the beginning again?

## ChatGPT

No. The producer should maintain a checkpoint for the input file.

A simple approach would be to archive the input batch and publish its records in bounded windows. After Kafka acknowledges all the records in a window, the producer saves the last acknowledged input position. The next time the import runs, it can continue from that position.

The checkpoint should identify the specific archived input, so it is not accidentally reused for a different file.

There is still a possible failure case where Kafka has accepted some messages but the producer stops before updating the checkpoint. Resuming the import could publish those messages again. Rather than trying to eliminate every possible duplicate publication, we should make downstream processing safe when duplicates occur.

It would also be useful to provide an explicit replay operation that reads the archived input again. That is different from normally resuming an interrupted import.

## User

How does the Kafka consumer know whether a paper has already been added to the database? Also, arxiv papers can have multiple versions. I don't want different versions of the same paper to show up as different papers when searching.

## ChatGPT

The canonical paper identity should be separate from its revision identity.

For example, `1234.56789v1` and `1234.56789v2` refer to revisions of the same arXiv paper. The stable paper ID would be `1234.56789`. Older arXiv identifier formats need to be handled as well.

The consumer should use the stable identifier to find the current paper record and then compare the incoming source version and update information with the stored metadata.

There are several cases we should explicitly handle:

| Incoming record | Expected behavior |
| --- | --- |
| Previously unseen paper | Insert the paper and its revision |
| Identical replay of a known revision | Reuse the revision and avoid duplicating the record |
| Newer valid revision | Update the current paper metadata |
| Older revision | Do not replace newer current metadata |
| Same source version and timestamp but different content | Detect the conflict and apply a documented policy rather than silently treating it as identical |

For exact duplicate detection, the normalized payload can be serialized consistently and compared with the existing revision. A database-generated numeric revision identifier would also give us a convenient way to refer to the accepted revision in other parts of the system.

The version comparison and database update should happen atomically. Otherwise, two updates to the same paper could both make decisions based on an outdated database state.

## User

Would this mean that we need to store every single version of a paper? Or can we just keep the latest version?

## ChatGPT

The search application only needs the current accepted version, but keeping a revision record is useful for replay and testing.

I would have a current paper record for each stable ID and a separate record for each accepted distinct revision. The current paper record would identify which revision is currently active.

That allows us to distinguish an actual update from an identical replay. It also gives us a way to identify whether an indexed document corresponds to the current version of the paper.

We do not need to build a user-facing interface for browsing every historical version. The additional revision information is mainly useful for maintaining the correctness of the pipeline.

## User

What happens if the consumer crashes after updating MySQL but before Kafka knows that it has processed that message?

## ChatGPT

Kafka may deliver the message again when the consumer restarts. That is why database processing needs to be idempotent.

The consumer should commit the relevant database transaction before committing the corresponding Kafka offset. If the database transaction fails, the consumer should not acknowledge that record as successfully processed.

If the database transaction succeeds but the consumer stops before committing the offset, the record can be processed again. Since the consumer recognizes an identical revision, it should not create another canonical paper or duplicate revision.

When processing records in batches, the consumer also needs to avoid committing a partition offset past an earlier record that has not been handled successfully.

This is an at-least-once processing design with idempotent database writes. I would describe it that way rather than claim that Kafka and MySQL together provide exactly-once delivery.

## User

Can you give me an idea of what tables we would need in the MySQL database? I don't want the database to become unnecessarily complicated.

## ChatGPT

I would start with four logical groups of tables:

- `papers`: the stable paper identity and its current accepted metadata or current revision reference.
- `paper_revisions`: accepted distinct metadata revisions and the information needed to distinguish them from repeated deliveries.
- `screening_projects`: the research topic or collection associated with a screening session.
- `screening_decisions`: the user's relevance labels and notes, associated with a screening project and a stable paper identifier.

If we want to preserve the history of screening decisions, we can store individual decision events instead of overwriting all previous decisions. The application can retrieve the latest decision for each project-paper pair.

These are logical responsibilities rather than a requirement that every implementation use exactly these table names. The important part is to have uniqueness constraints for paper identity and revision identity, and to prevent a decision from being associated with a nonexistent paper or screening project.

## User

When a paper is updated, will the relevance labels that the user previously made on that paper still be there?

## ChatGPT

Yes. A screening decision should reference the stable paper ID rather than a particular search index entry or a temporary row number in the search results.

If a paper has a new abstract or title, the current metadata can change without deleting the screening decision. Likewise, rebuilding the BM25 or semantic index should have no effect on the saved decision because it is stored independently in MySQL.

A paper can also have different decisions in different screening projects. The latest decision should be looked up using both the screening project ID and the paper ID.

The search results can show those decisions alongside the current paper metadata. They should not automatically change the labels merely because the ranking or metadata changed.

## User

For the search functionality, should BM25 and semantic search be part of MySQL or should they be separate from the database?

## ChatGPT

I would keep the search indexes separate from MySQL while using MySQL as the authoritative source of their input data.

The BM25 index should contain searchable text from each current paper, primarily its title and abstract. Depending on the tokenizer, it may also be useful to give title matches more weight and preserve technical identifiers or hyphenated terms.

The semantic index should contain vectors generated from the same general paper content using a sentence embedding model. The query is encoded with the compatible model, and the documents are ranked by similarity to the query vector.

Both indexes need to retain a mapping between their document entries and the stable paper IDs. They should also have enough revision or snapshot information to identify which version of the metadata they represent.

The application can use those IDs to retrieve authoritative paper details and screening decisions from MySQL.

## User

Do we need to rebuild the entire search index every time a new paper gets added? That seems like it would take a long time, especially for semantic search.

## ChatGPT

Not necessarily. I would start with a reliable full-build workflow and then introduce incremental refresh where it is useful.

BM25 depends on corpus statistics, so the implementation needs to make sure those statistics stay consistent when documents change. A complete rebuild can be an acceptable initial approach on a small corpus if its runtime is measured and documented.

Semantic indexing is more expensive because each document has to be encoded. We should avoid regenerating embeddings for unchanged documents when possible. A stored embedding should only be reused when its input text and embedding model are still compatible with the current configuration.

For either mode, the index should not become visible to search requests while it is only partially built. We can build a new index or index generation and switch to it after the build has successfully completed.

If MySQL has newer metadata than the index, the application should be able to report that the index is not fully current. We should also avoid presenting a result as if it were ranked using the latest paper revision when the actual indexed document is stale.

## User

Can the index be updated directly by the Kafka consumer at the same time as it updates the database? Wouldn't that be a simpler approach?

## ChatGPT

It might appear simpler, but it introduces a consistency problem because the database update and the search index update are separate operations.

For example, the consumer might successfully commit a paper to MySQL and then fail while updating its search index. If the two operations are treated as one successful update without a way to detect and repair the difference, the index could remain stale.

I would keep the consumer focused on committing canonical metadata and give indexing a separate refresh workflow. That workflow can use the current revision information in MySQL to detect new or changed records and rebuild or update the derived search data.

For the first version, the refresh can be triggered explicitly after an ingestion run. We can add automatic background refresh later if it is necessary. The user should not have to reimport all the source data to repair a failed index build.

## User

How much complexity do we need for semantic search? Would we need a separate vector database?

## ChatGPT

A separate vector database is not necessary for the initial local version.

We can use a small CPU-compatible sentence embedding model to encode paper titles and abstracts and store the vectors locally with their corresponding paper IDs. Depending on the size of the collection, a local vector search implementation can rank the vectors by cosine similarity.

It is important to keep the model configuration, input text format, and stored vectors consistent. Query embeddings and document embeddings need to follow the selected model's retrieval conventions.

For larger collections, embedding generation time and memory usage may become limiting factors. We should measure those before deciding whether a more sophisticated vector indexing solution is justified.

## User

How would the user interface communicate with all these components? Can Streamlit directly access the database and run the search methods?

## ChatGPT

Streamlit could do those things directly, but I would prefer to put a small FastAPI service between the interface and the underlying system.

Streamlit would be responsible for collecting the query, displaying the results, and letting the user manage screening decisions.

FastAPI would provide operations for searching papers, retrieving paper metadata, creating or opening screening projects, saving decisions, and exporting results. It would coordinate access to MySQL and the search indexes.

This separation gives the system a clearer boundary. We can test the search and screening operations without opening the UI, and we do not have to duplicate database access or search logic in the interface.

The ingestion producer, Kafka consumer, Spark job, and index-building commands can remain separate processes. The API does not need to manage every data engineering operation itself.

## User

I still want Spark to be a substantial part of the project. Can you explain in more detail how the Spark batch processing should work?

## ChatGPT

One useful batch-processing workflow would be to take an existing Parquet snapshot and another batch of paper metadata records, then produce a merged Parquet snapshot.

The job should normalize the input schema, derive the stable paper ID, remove exact duplicate records, and determine the latest valid revision for each paper. It should use a deterministic version ordering and handle conflicting records according to the documented policy.

The result should contain the expected current record for each paper. We can verify it against a controlled fixture where we already know the expected output, including repeated records, newer revisions, and older revisions that should not replace the current version.

The Spark job should write a separate output snapshot rather than modifying the input snapshots in place. That makes the batch experiment reproducible and allows us to compare different processing approaches.

If we compare CSV and Parquet, both inputs should represent the same logical records. We should check the outputs for equivalence before comparing processing time, storage size, or other performance measurements.

## User

Do we need HDFS for Spark? We used HDFS in CS544, but I feel like using both HDFS and local storage would make things more complicated.

## ChatGPT

I would leave HDFS out of the initial architecture. Spark can run in local mode and read and write Parquet files on the local filesystem.

You would still demonstrate Spark DataFrame operations, schema management, batch transformations, deduplication, and columnar storage. HDFS would add another infrastructure component but would not necessarily make those demonstrations better on a single machine.

The documentation should make it clear that this is a local Spark workload, not a distributed storage or multi-node execution experiment.

## User

How many Docker containers would we need for this project? Should we put every part of the program in Docker?

## ChatGPT

I would use Docker Compose for the infrastructure services, particularly Kafka and MySQL. That gives us reproducible service configuration and named volumes for persistent data.

Depending on the Kafka image, the broker can run using KRaft without a separate ZooKeeper container. For the application itself, there are two reasonable options: run the Python processes locally using one documented environment, or package them into containers if that makes setup easier.

I would not create a separate container for every function just to increase the number of services. The producer, consumer, index builder, API, and Streamlit interface have separate responsibilities, but that does not require each to have a separate image.

The local Spark job can also be run independently. The main requirement is that every component has a reproducible startup procedure and uses the correct configuration and persistent storage paths.

## User

How should we organize the files in the project? I want it to be relatively easy to understand when someone else looks at the GitHub repo.

## ChatGPT

I would organize the repository around the responsibilities of the components rather than put all of the logic into one application file.

For example, a possible structure would be:

```text
PaperSearch/
├── ingestion/         # Input parsing, producer, consumer, replay
├── storage/           # MySQL schema and persistence logic
├── search/            # BM25, semantic search, index refresh
├── batch/             # Spark and Parquet processing
├── api/               # FastAPI operations
├── ui/                # Streamlit reviewer
├── tests/             # Unit and integration tests
├── fixtures/          # Small deterministic input datasets
├── scripts/           # Setup and experiment entry points
├── docs/              # Architecture, setup, and evaluation
├── docker-compose.yml
├── .env.example
└── README.md
```

This is a suggested structure, not a strict requirement. Shared utilities can be placed in a common Python package when multiple components actually need them. Configuration, database connection logic, and record normalization are good candidates for reuse.

Generated data, large metadata archives, embeddings, database volumes, and local credentials should not be committed to Git. The repository should contain enough source code, configuration, documentation, and small fixtures to reproduce the intended workflow.

## User

Can you explain the complete flow of the program using an example? I want to make sure I understand what happens from the time we import the papers to when the user is able to search for them.

## ChatGPT

Suppose we have an input batch containing three new papers.

1. The ingestion producer reads the records from the input file, archives the batch, and publishes each record to Kafka using the stable paper ID as the message key.
2. The metadata consumer reads the messages, checks whether each paper or revision already exists, and commits the appropriate changes to MySQL before acknowledging processing to Kafka.
3. The index refresh workflow reads the current paper metadata from MySQL and builds or updates the BM25 index and semantic index.
4. The user opens the Streamlit interface and enters a research query. Streamlit sends the query and selected search mode to FastAPI.
5. FastAPI runs the selected search method, retrieves the corresponding paper metadata and existing screening decisions, and returns a ranked list.
6. If the user labels a paper, FastAPI saves that decision in MySQL. The paper's ranking is not changed merely because a label was saved.

Now suppose a subsequent input batch contains a new revision of one of the three papers and an identical copy of another. The consumer should accept the new revision, recognize the identical copy as a replay, and retain the existing screening decisions. The search index refresh should make the accepted current metadata searchable.

Separately, the Spark batch job can merge corresponding archived or Parquet inputs into a new snapshot and verify the expected latest records. It does not need to be part of the path for answering each individual search query.

## User

How can we tell whether the whole pipeline is actually working as expected? For example, publishing a message to Kafka doesn't necessarily mean that I can immediately search for that paper.

## ChatGPT

We should distinguish three milestones when measuring the pipeline:

- Kafka acknowledged: the producer has received confirmation that the record was accepted by the broker.
- MySQL durable: the consumer has successfully committed the record to the database.
- Search visible: the relevant index generation has made that accepted revision available for search.

Recording these milestones separately allows us to measure publication throughput, the time needed for consumer processing, and the delay before a paper is searchable.

The tests should also verify correctness, not just timing. A useful integration scenario would ingest a fixture, interrupt and restart processing, replay an input batch, ingest a revision, refresh the search indexes, and verify that the final paper records and screening decisions match the expected state.

For comparing the two search modes, we should use the same declared candidate collection and relevance judgments, and report any difference in index coverage. We should not assume that every stored paper has a semantic embedding just because it exists in MySQL.

## User

I think the architecture looks good. I don't want to add any other technologies unless there is a clear reason for them. Can we move on to planning how to implement the project step by step?

## ChatGPT

Yes. We can keep the architecture focused on Kafka for ingestion, MySQL for current metadata and screening history, Parquet and local Spark for batch processing, BM25 and CPU-based semantic search for retrieval, and FastAPI and Streamlit for the reviewer application.

The first implementation milestone should be a small working ingestion pipeline with a deterministic fixture and persistent database records. After that is verified, we can add replay and revision handling, the search indexes, the screening application, the Spark workflow, and the larger-data experiments.

Each milestone should have a concrete test or demonstration that shows the expected behavior before we move on to the next one. That will make it easier to identify which part of the system is responsible if something stops working later.
