# PaperSearch — Idea Development

## User

I asked the professor of this class to write a recommendation letter for my masters application. To write an outstanding recommendation letter for me, the profess asked me to do an personal project. Here is what she included in the email:

- Detailed documentation, code, and video walkthrough from a personal project related to CS544 course material. This needs to be done outside of any other coursework, and the project idea must be related to the course content (that is, you must demonstrate how you have applied the skills you learnt in the course to your personal project). I need the following details:
  - A git repository that shows the commit history.
  - If you do use AI platforms, git repo should include transcripts of your chat history, along with clear comments for any AI-generated code.
  - Short video (5 minutes maximum) walk-through of your project code explaining the code and showing a demo. In the video, you must both share your screen and have your camera turned on.

Considering my past experiences, including my Computer Science and Statistics background, AI/ML, past projects, etc. Give me some ideas for this project that can be outstanding to the professor and graduate admissions committee, and possibly my CV.

## ChatGPT

I would focus on building a complete data system that solves a practical problem, rather than a machine learning project that happens to use some of the technologies from CS 544.

Here are a few possible directions:

1. **Research paper search and screening system.** Collect research paper metadata, process incoming updates, support different search methods, and allow researchers to track which papers they have reviewed.
2. **Model inference monitoring pipeline.** Collect latency, throughput, and error measurements from model inference requests and use a streaming and batch processing pipeline to analyze them.
3. **Large-scale document retrieval system.** Ingest and process a document collection, support keyword and semantic retrieval, and evaluate the performance of the system as the collection grows.

The first idea would connect your AI research interests with the data engineering concepts covered in CS 544. The second would connect well with your compiler internship. The third would give you room to explore retrieval and evaluation.

Whichever direction you choose, the main thing is to demonstrate that you understand the purpose of each data system component and how they work together.

## User

The research paper idea is relevant to something I was doing recently. I was learning about a new research topic, VLM KV cache, and throughout the process, I found that finding relevant papers when researching a new problem can be pretty time consuming. Can I build an app where the user enters a research topic and the program automatically finds and recommends relevant papers?

## ChatGPT

Yes. You could build a system that maintains a searchable collection of research papers using metadata such as titles, abstracts, authors, publication dates, and arXiv identifiers.

For a literature review on VLM KV cache, you might search for terms such as `VLM KV cache`, `multimodal cache compression`, or a particular paper title. The system could return relevant papers and allow you to keep track of the ones you have already examined.

The project would have two main parts:

- A data pipeline that ingests, processes, updates, and stores research paper metadata.
- A user-facing application that searches the collection and supports literature screening.

The data pipeline should be the main technical contribution for CS 544. The application would demonstrate that the pipeline serves a useful purpose.

## User

How would this be different from just searching on Google Scholar or arxiv? I don't want the project to simply be another paper search engine.

## ChatGPT

You could narrow the scope to managing a literature review rather than trying to compete with an existing academic search engine.

For example, suppose you are reviewing papers about a particular research topic. You might want to mark papers as relevant or irrelevant, retain those decisions, and search the collection again after new papers are added. Your system could support that workflow.

The more important distinction for this project would be how the underlying data is managed. You could demonstrate what happens when the same paper arrives multiple times, when an existing paper is updated, or when the ingestion process is interrupted.

Those are data engineering problems that directly connect to CS 544 and are not visible in an ordinary search application.

## User

I like the idea of being able to label the papers as relevant or irrelevant. Would the labels still be there after I close the program and open it again? Also if I add more papers into the database, I don't want the labels on the existing papers to disappear.

## ChatGPT

Yes. The screening decisions should be stored persistently in a database, separately from the searchable paper index.

Each paper should have a stable identifier, such as its arXiv ID. A relevance label can be associated with that identifier, so rebuilding the search index or importing additional papers would not erase the label.

You could also retain the history of screening decisions if you want to track how a paper's relevance assessment changes. For the initial version, the important requirement is simply that the latest decision remains available after a restart or data refresh.

## User

What materials from CS544 can we apply to this project? I want to use Kafka and Spark if possible, but I don't want to include technologies just for the sake of using them.

## ChatGPT

Kafka and Spark both have reasonable roles in this project.

Kafka could handle the ingestion of new and updated paper records. Instead of writing directly from the data source into every downstream system, you could publish records to a topic and consume them independently. That gives you an opportunity to demonstrate message processing, consumer recovery, and replay.

Spark could handle batch processing of archived paper records, such as merging snapshots, deduplicating records, and selecting the latest version of each paper. Parquet would be a useful storage format for those snapshots.

A relational database such as MySQL could hold the current paper metadata and screening decisions. Docker could make the system reproducible and easier to demonstrate.

I would avoid adding Cassandra or another database unless you can identify a separate workload that actually benefits from it.

## User

For the actual paper search, can we have both keyword search and semantic search? Sometimes I know the exact name of the model or paper I am looking for, but sometimes I only know the general idea.

## ChatGPT

That is a good reason to support two search modes.

BM25 keyword search would be useful for exact paper titles, model names, and technical terms. Semantic search using text embeddings would allow you to search by the meaning of a query even when the papers use different terminology.

You could start with BM25 as the default and provide an option to switch to semantic search. This would be simpler to implement and evaluate than immediately combining both rankings into a hybrid search system.

The search features would complement the data pipeline, but they do not need to become the main focus of the project.

## User

Would I need to use a GPU for the semantic search? I want to make sure the whole project can be run locally.

## ChatGPT

Not necessarily. A relatively small sentence embedding model can run on a CPU, especially if you start with a manageable paper collection and precompute the embeddings.

You can keep the initial project local and use a small offline dataset to demonstrate the complete workflow. A larger dataset can be used later to evaluate ingestion, indexing, and search performance.

It is also useful to separate the time required to build an index from the time required to execute an individual search. Those are different workloads and can be measured independently.

## User

I think we should focus on this project. I want the main purpose to be helping with finding and screening research papers, while using the project to demonstrate the things I learned from CS544. What should be the core expected functions of the project?

## ChatGPT

I would define the core functions as follows:

1. Ingest research paper metadata from an offline dataset or arXiv data source.
2. Publish and consume paper records through Kafka, including handling repeated records and interrupted processing.
3. Maintain persistent paper metadata and relevance labels in a database.
4. Archive records in Parquet and use Spark for batch merging and deduplication.
5. Provide BM25 keyword search and CPU-based semantic search.
6. Provide a simple interface for searching papers and recording screening decisions.
7. Verify that replay, updates, and restarts do not lose data or screening decisions.

A suitable project name would be **PaperSearch**. The next step would be to turn these functions into an architecture, identify the responsibilities of each component, and define a manageable implementation plan.
