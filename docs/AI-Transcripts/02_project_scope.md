# PaperSearch — Project Scope

## User

Let's go with PaperSearch. Before we start planning the architecture, I want to have a clear understanding of what we are actually trying to build. What should be included in the project scope?

## ChatGPT

I would define PaperSearch as a local research paper discovery and screening system backed by a data pipeline that supports incremental updates and recoverable processing.

The application should allow a researcher to:

- Search a collection of research papers using a topic, technical term, or paper title.
- Switch between keyword search and semantic search.
- View paper titles, abstracts, authors, and publication information.
- Mark papers as relevant or irrelevant and record notes.
- Return to a previous screening project without losing decisions.
- Export screening results for further use.

Behind the application, the system should be able to ingest paper metadata, handle updates and repeated records, store data persistently, and rebuild its derived search data when necessary. This is the part that should demonstrate the skills from CS 544.

## User

Where should we get the research papers from? Do we need to download the actual PDF of every paper?

## ChatGPT

I would use an arXiv bulk metadata snapshot as the initial data source. It provides the information needed for searching and screening papers without requiring you to download their full text.

For the initial scope, you only need fields such as:

- arXiv identifier
- Title and abstract
- Authors and categories
- Publication and update information, where available
- Link to the original paper

Downloading and processing every PDF would significantly increase storage requirements and processing time. It would also introduce document parsing problems that are not necessary for demonstrating the data pipeline.

The user can follow the original paper link when they want to read the full paper. Search and screening can initially operate on titles and abstracts.

## User

Since arxiv has a lot of papers, how many papers should we be working with? I want the project to demonstrate that it can handle big data, but everything is going to be running on my local computer.

## ChatGPT

I would separate the amount of data needed for development from the amount needed for evaluation.

| Dataset size | Purpose |
| --- | --- |
| Around 1,000 records | Develop and test the complete workflow locally |
| 10,000 records | Verify the pipeline at a larger scale |
| 50,000 records | Observe processing time and resource usage |
| 100,000 records | Target for a working larger-scale application and benchmark |
| 1 million records or more | Optional expansion if the previous stages are successful |

The eventual goal can be to process the full eligible metadata collection from one fixed arXiv snapshot. However, I would not make that a requirement for the first working version.

In particular, generating semantic embeddings for every paper may take much longer than storing metadata or building a keyword index. The project can report the amount of data covered by each search mode separately instead of pretending that all stages necessarily cover the same corpus.

## User

Would the initial dataset just be loaded into MySQL directly? If that's the case, what is the purpose of Kafka in this project?

## ChatGPT

The initial import should exercise the same ingestion workflow used for subsequent updates. The bulk dataset can be read in bounded batches, and paper records can be published to Kafka before they are processed and stored in MySQL.

That way, Kafka is not simply an additional tool attached to an otherwise complete application. It is part of the normal path by which paper records enter the system.

The scope should include demonstrating that the pipeline can recover if a consumer stops while processing records. It should also handle records being delivered more than once without producing duplicate canonical papers or losing screening decisions.

A local single-broker Kafka setup is sufficient to demonstrate consumer recovery and replay. It should not be presented as protection against permanent loss of the broker's disk or as a highly available distributed deployment.

## User

I also want the database to be updated when new papers come out. Do we need to have it automatically collect papers every day?

## ChatGPT

Automatic daily collection can be a future improvement, but it does not need to be a requirement for the project.

For the initial version, support importing a dataset and then ingesting another batch that contains new papers, revised papers, and repeated records. The resulting collection should reflect those updates correctly.

A small controlled update batch would be especially useful for the demonstration because you can know exactly which records should change and which should remain unchanged.

The important requirement is that the update workflow works correctly. A continuously running crawler or scheduler is not necessary to establish that.

## User

For the user interface, I don't want anything too complicated. I mainly want the user to enter the topic, view the returned papers, and label them. I also want the user to be able to come back to the same topic later.

## ChatGPT

A simple screening interface should be sufficient. A typical workflow would be:

1. Create or open a screening project associated with a research topic.
2. Enter a query and choose the search mode.
3. Browse the returned papers and read their abstracts.
4. Mark individual papers as relevant or irrelevant, and optionally add notes.
5. Reopen the project later and see the previously saved decisions.
6. Export the screening results as a CSV file.

Decisions should belong to a screening project and a stable paper identifier. The same paper might be relevant to one research topic but irrelevant to another, so a single global relevance label would not be appropriate.

The interface does not need user accounts, collaboration, or elaborate visual design. A local application that supports the complete workflow is enough for this scope.

## User

For the two search methods, should we combine the keyword and semantic search results together or just give the user an option to choose between the two?

## ChatGPT

I would start with BM25 as the default search method and provide an option to switch to semantic search. Each query should display one ranked list for the selected mode.

BM25 should work well when the query contains specific technical terms, model names, or a paper title. Semantic search should help when the user describes a research problem using different wording from the papers themselves.

Keeping the two methods separate also makes it easier to compare their retrieval quality. Combining them into a hybrid ranking would introduce additional decisions about score normalization or rank fusion.

For the initial scope, both search methods should operate on available indexed titles and abstracts, support the same relevant filtering options, and return paper records that can be screened. Hybrid search can remain outside the required features.

## User

When the user labels a paper as relevant or irrelevant, should the program learn from those labels and improve the search results in the future?

## ChatGPT

That could be a useful extension, but I would not include it in the required scope.

For the current project, screening labels and notes should be persistent records of the researcher's decisions. They should remain associated with the correct project and paper after restarting the program, refreshing the dataset, or rebuilding search indexes.

Training a relevance classifier or modifying rankings based on user feedback would turn the project into an additional machine learning problem. It would require enough labeled data and a separate evaluation to determine whether the feedback improves retrieval.

Saving the labels and making them available for review and export is sufficient for the initial version.

## User

What should Spark be doing? I want it to be a meaningful part of the project as well.

## ChatGPT

Spark should have a separate batch-processing responsibility rather than being used for every interactive search or individual paper update.

One suitable workload is to merge a previously archived paper snapshot with a batch of changes, identify repeated records, and determine the latest valid versions. This would demonstrate working with larger datasets, transformations, and Parquet storage.

You could also compare a batch-processing workload on equivalent CSV and Parquet datasets. The comparison should use the same logical input records and verify that the resulting data is equivalent before comparing runtime or storage size.

Spark should work on explicit batch inputs and outputs. It should not independently overwrite the live database or create a second conflicting update path.

## User

How should we evaluate this project? I want to be able to show actual results rather than just demonstrate that the program is running.

## ChatGPT

I would evaluate three aspects of the project.

**1. Data correctness and recovery.** Use controlled inputs with repeated records and known changes. Check that the final records match the expected results, that interrupted processing can resume, and that screening decisions survive restarts and index rebuilds.

**2. Data processing performance.** At each dataset size, record ingestion throughput, processing time, memory usage, storage growth, and any processing backlog. For ingestion timing, distinguish when Kafka acknowledges publication, when MySQL has durably stored the data, and when the data becomes visible in search. Those are different milestones.

**3. Search quality.** Compare BM25 and semantic search using a fixed set of queries and relevance judgments over the same declared candidate collection. A metric such as Recall@50 can show how many known relevant papers are retrieved. If an external screening dataset is used, document what its labels actually represent and which records are included in the comparison.

The search evaluation should not claim to identify all relevant papers on arXiv. It should describe performance on the evaluated collection. Likewise, relevance based on a title and abstract is not necessarily the same as a final inclusion decision made after reading the full text.

## User

I don't want this project to get too big. What should we explicitly not include in the project?

## ChatGPT

I would leave the following outside the required scope:

- Downloading, parsing, or indexing full-text PDFs.
- LLM-generated paper summaries, answers, or a RAG chatbot.
- Citation graph analysis.
- Hybrid search or a model trained from screening feedback.
- User authentication, multi-user collaboration, and cloud deployment.
- Cassandra, HDFS, or a multi-node Spark cluster unless a specific need arises later.
- Continuous real-time collection of every newly published arXiv paper.

These are reasonable future extensions, but none is necessary for the core research screening workflow or the data engineering demonstration. It is better to complete and test the smaller system than to include many partially functioning components.

## User

Can you define what we should have completed before considering the project done? Also, considering that the professor requires a video of no more than 5 minutes, I want to make sure I can actually demonstrate the main features.

## ChatGPT

I would use the following completion criteria:

1. A fresh local installation can run a small offline fixture through the complete pipeline.
2. Kafka ingestion handles repeated records and recovery after an interruption correctly.
3. New and revised paper records are reflected in the stored collection and available search data.
4. Both BM25 and CPU-based semantic search return usable ranked results, with coverage and freshness limitations made clear.
5. Screening projects, labels, notes, and CSV export work, and saved decisions survive restarts and data updates.
6. Parquet snapshots and a local Spark batch merge demonstrate a separate batch-processing workflow with verified results.
7. The larger-data experiments report actual measurements at the completed dataset sizes, with 100,000 records as a target rather than a claim of an already achieved result.
8. Documentation explains how to run the project, what each component does, how it was tested, and its limitations.

For the video, you could demonstrate the offline fixture rather than importing the entire larger dataset on camera. Show the initial search, save a screening decision, ingest a small update batch, and verify the stored results. Briefly show the Kafka and Spark workflows, and use the remaining time to explain the measured results and important recovery tests.

The repository should also retain the actual development history and records of AI assistance required by the professor.

## User

That sounds like a reasonable scope. I think we should first make sure the whole program works on a smaller dataset and then increase the dataset size. I don't want to sacrifice correctness just to work with more papers.

## ChatGPT

That is a useful way to prioritize the work. Establish a complete, reproducible small-data workflow first. Then expand the dataset only when the previous stage has been verified.

At each expansion stage, monitor throughput, memory, database and volume growth, remaining disk space, processing backlog, and final record counts. If a larger run exceeds the machine's resources or fails a correctness check, preserve the last verified result and document the limitation before attempting another expansion.

The project scope is now sufficiently defined to move on to system architecture. The next step is to decide which components own the data, how records move between them, and how the search indexes and screening interface interact with the persistent database.
