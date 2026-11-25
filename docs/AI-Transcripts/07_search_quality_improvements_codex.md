# PaperSearch — Search Quality Improvements

## User

Other than checking if the whole program works as expected, I also want to make sure that the returned papers are actually relevant to what the user searches for. This is basically the main purpose of the application. I want to go over the problems we encountered with search in the earlier version of PaperSearch and make sure we have a general solution for them.

For example, when I searched `VLM KV Cache`, a lot of the papers returned by the program were not related to VLM KV cache at all. There are some papers I already know about, such as LOOK-M and VL-Cache, but they were not appearing in the search results. Can you figure out why this would happen?

## Codex

I would separate this into two problems before changing the ranking code:

1. Are the relevant papers actually present in the searchable collection?
2. If they are present, is the search implementation ranking them appropriately?

The distinction is important. If a paper has never been included in an index, no amount of adjustment to the ranking algorithm will make that paper appear in the results.

The earlier search review found that the reviewer was using a BM25 index containing approximately 100,000 papers. Two papers that were useful for checking the VLM KV cache query were missing from that index:

| Paper | arXiv ID |
| --- | --- |
| LOOK-M | `2406.18139` |
| VL-Cache | `2410.23317` |

The returned papers were therefore being selected from a collection that did not contain some of the papers you expected to find. At the same time, a BM25 query containing several terms could retrieve papers that matched only part of the query, such as papers discussing an unrelated type of cache.

This suggests that the first problem was not necessarily the BM25 scoring formula itself. We need to check index coverage and the way search terms are handled together.

## User

If those papers are not in the index, are they missing from the actual data that we downloaded from arxiv or just the data that we are currently using for the search?

## Codex

Those are different possibilities. PaperSearch has several stages between the source data and the results displayed in Streamlit:

```text
Source metadata
    -> Kafka ingestion
    -> Current paper records in MySQL
    -> Eligible index input records
    -> Published search index
    -> API search results
    -> Streamlit reviewer
```

A paper can be present at one stage and missing at a later stage. For example, the paper might be present in the original metadata file but excluded by an import limit, or it might exist in MySQL but not yet be included in the published index.

I would check the two known arXiv IDs at each boundary and record where they stop appearing. For the semantic index, I would also check whether each paper has a compatible embedding for its accepted current revision.

The earlier review established that the two papers were absent from the active 100,000-paper lexical index. That alone does not establish that they were absent from every source file or database.

We should also compare the number of records in MySQL with the number of unique papers represented by the active search artifacts. The reviewer should not assume that all imported papers are searchable through both modes.

## User

I think we should first fix the BM25 search. What do we need to change to make it work better? I don't want to make the ranking algorithm too complicated.

## Codex

I would keep BM25 and concentrate on the input collection and the way the query is interpreted. There is no need to replace the search algorithm simply because the initial results were poor.

The implementation should be reviewed for the following behaviors:

- Both document text and queries are normalized using compatible rules.
- Titles and abstracts are included in the searchable fields.
- Exact titles and distinctive method names are not lost during tokenization.
- A title match receives appropriate importance without making abstract matches irrelevant.
- Multi-term queries use evidence from the different terms rather than allowing a common term to dominate every result.
- Search results map back to the correct stable paper IDs and current metadata.

For a query such as `VLM KV Cache`, a document that discusses vision-language models and KV cache management should generally receive stronger evidence of relevance than a document about an unrelated file cache.

That does not mean that we should require every result to contain every query word. A relevant paper might use the full phrase `vision-language model` rather than the acronym `VLM`, or discuss key-value cache compression using different terminology.

Before changing multiple parts of the scoring logic, I would use a small fixture to establish which behaviors are currently incorrect. That will help us keep the changes limited to the actual problems.

## User

For example, if I search the name of a paper like LOOK-M, I expect that specific paper to be returned first. How do we handle names like that with BM25?

## Codex

Method names containing punctuation or hyphens are worth testing explicitly. Depending on the tokenizer, `LOOK-M` may become the separate tokens `look` and `m`. Neither token is especially distinctive on its own.

A general approach is to preserve a normalized representation of the paper title and its technical identifiers in addition to the ordinary searchable tokens. The normal BM25 ranking can then be supplemented by consistent title or phrase-match evidence when the query is sufficiently specific.

The important point is not to give LOOK-M a special rule. The same behavior should work for other hyphenated method names, acronyms, model names, and complete paper titles.

An earlier offline check used a small collection containing LOOK-M, VL-Cache, and ZipVL. It found that exact method-name queries ranked the corresponding papers first, and the query `VLM KV Cache` returned those three papers at the top of the small test collection.

That was useful evidence that the approach could work on controlled inputs. It did not establish that the live reviewer had been updated or that the same ranking quality would hold on the full corpus. Publishing the updated live index was blocked during that check.

## User

Would this only make the searches LOOK-M and VL-Cache work? Or would it fix the whole general issue? I don't want to have anything hard coded specifically for those papers.

## Codex

Those papers should be regression examples, not production rules.

The search implementation should not contain branches that check for `LOOK-M`, `VL-Cache`, or `VLM KV Cache` and manually insert particular paper IDs into the results.

To check generalizability, I would use several types of queries from different research areas:

| Query type | Example | Expected behavior |
| --- | --- | --- |
| Method name | `LOOK-M` | Find the named method when indexed |
| Hyphenated name | `VL-Cache` | Preserve meaningful identifier matching |
| Complete title | `Attention Is All You Need` | Rank the matching title highly when present |
| Multi-term topic | `speculative decoding language models` | Prefer papers addressing the combined topic |
| Technical acronym | `LoRA fine tuning` | Retrieve papers on the relevant method |
| Another research area | `conformal prediction uncertainty` | Apply the same retrieval logic outside VLM research |

The test corpus should contain relevant and irrelevant examples for each case. We should also test what happens when a named paper is genuinely absent from the index.

A successful change should improve the general ranking behavior and preserve existing useful results. Passing two specific queries is not enough to conclude that the overall problem is fixed.

## User

If we increase the size of the BM25 index, would that solve most of the problem? We have a lot more arxiv data than the 100,000 papers that we initially used.

## Codex

Increasing the index size can solve the coverage problem, but it is not a guarantee of better ranking quality.

The earlier follow-up review reported that the lexical index had expanded to 451,283 papers. This gave the search engine a much larger candidate collection than the original 100,000-paper index.

However, larger collections also contain more documents that partially match a query. We should continue to evaluate the ranking rather than assume that adding records automatically improves the top results.

The expansion should follow the project's existing workflow:

1. Ingest and verify the intended metadata collection.
2. Build the lexical index from the declared eligible records.
3. Validate the index and its paper-ID mapping.
4. Publish the completed generation.
5. Run the same representative queries against that generation.

For evaluation, record the index generation and document count alongside the search results. Otherwise, we may accidentally compare results from two different collections and attribute the difference entirely to a ranking change.

## User

Ok, the BM25 search looks better now, but it seems like the semantic search is still not working. When I search the same topic, the returned papers don't seem to have anything to do with the topic. Can you check what the problem is with the semantic search?

## Codex

The earlier semantic search review found a substantial coverage problem.

At that stage, the lexical index had 451,283 papers, but the active semantic index contained only 4,878 papers. The semantic collection consisted of papers from 2007–2008, and its construction used a 5% hash-based sampling rule that excluded the expected VLM KV cache papers.

That explains why changing the query wording or adjusting the cosine similarity calculation alone could not solve the original problem. The relevant modern papers were not available to the semantic ranking in the first place.

I would check the semantic workflow in this order:

1. Which records are selected for embedding generation?
2. How many embeddings are available, and what publication periods do they cover?
3. Are the desired papers represented by compatible vectors?
4. Are the document and query encoding settings consistent?
5. Is the similarity ranking and vector-to-paper mapping correct?
6. Is the API using the intended published index generation?

The earlier review also performed an in-memory comparison involving embeddings for LOOK-M, VL-Cache, and ZipVL. Those papers scored above the existing semantic results in that check. That supports the explanation that candidate coverage was a significant problem.

The in-memory experiment did not update the active index or application, so it should not be treated as evidence of a completed live fix.

## User

Why were we only generating embeddings for 5% of the papers? I understand that the runtime can be long, but randomly taking a small portion of the dataset means that a lot of the relevant papers might not be there.

## Codex

Sampling can make an initial embedding benchmark manageable, but it is not a good substitute for a usable research collection.

If sampling is applied to an already time-limited input selection, the resulting index can be much narrower than the user expects. In the earlier semantic index, the combination of limited input coverage and sampling excluded modern VLM papers entirely.

For development, we can still use a small deterministic fixture to verify the complete semantic workflow. For the application, the indexed collection should be selected according to a documented policy that matches the intended search scope.

The options are to generate embeddings for the full eligible collection, or to maintain an explicitly limited semantic collection while additional papers are processed. The second option is acceptable if the interface makes the limitation clear.

I would remove arbitrary sampling from the normal production index-building path unless there is an explicit reason for it. If we retain a sampling option for benchmarking, it should be separate from the ordinary application configuration.

## User

Does that mean we have to generate the embeddings for every paper before the semantic search can be used? There are millions of papers in the dataset and this could take a very long time on my computer.

## Codex

No. The program can support partial semantic coverage while continuing to provide BM25 search over the larger collection.

The important distinction is between incomplete coverage and incorrect results. A partially built semantic collection can still return a valid ranking over the documents it contains. It cannot rank documents for which it has no usable embeddings.

For that reason, I would keep BM25 as the default search mode and make semantic search an explicitly selectable alternative. The user should be able to see how many papers are covered by each mode.

Embedding generation can proceed in bounded batches. For unchanged paper content and a compatible model configuration, previously generated vectors can be reused. New or changed current revisions should be processed through the existing embedding work mechanism.

The index should become available only when a usable generation has been published. We should not let a search request read a half-written vector file or a partially updated paper-ID mapping.

This makes it possible to improve semantic coverage without blocking the entire application until every embedding has been generated.

## User

Other than the issue of the papers not being in the semantic index, are there any problems that could be related to the embedding model or the way we are generating the embeddings? I want to make sure that once the relevant papers are included, the actual semantic search works correctly.

## Codex

Yes. Once coverage is established, I would check the encoding and ranking pipeline before deciding whether to change the model.

The document input should contain the intended title and abstract, with consistent formatting. The query encoder should use the same compatible model configuration and follow the retrieval conventions of that model. Some models expect different prefixes or instructions for queries and documents, so this needs to match the selected model rather than be guessed.

For the ranking itself, I would check:

- Query and document vectors have compatible dimensions.
- Vectors contain finite values and satisfy the normalization requirements of the similarity calculation.
- The similarity scores are sorted in the correct direction.
- Each vector row is mapped back to the intended paper ID and revision.
- The index metadata identifies the embedding model and input representation used to construct it.
- Updated documents are not silently represented by embeddings from an older revision.

A useful small test can use known vectors to verify the similarity and ordering logic without loading the embedding model. A separate retrieval test should use the actual model and representative paper texts.

I would not immediately switch to a different embedding model. Changing the model would require regenerating incompatible vectors, and it would make it harder to identify whether the original problem came from coverage, encoding, or ranking.

## User

What about acronyms like VLM? If the paper doesn't say VLM anywhere in the abstract but instead says vision language model, I would still want the semantic search to return it. Isn't that supposed to be the purpose of semantic search?

## Codex

Yes. Semantic retrieval is intended to reduce the dependence on exact word matching, but that does not mean that every embedding model will treat all equivalent query formulations identically.

Short technical queries can be particularly sensitive to wording because they provide very little surrounding context. An acronym can also be ambiguous unless the model has enough information to interpret it in the intended research area.

A later search check in PaperSearch showed this difference:

| Query | Search mode | VL-Cache rank | LOOK-M rank |
| --- | --- | ---: | ---: |
| `VLM KV Cache` | BM25 | 3 | 8 |
| `VLM KV Cache` | Semantic | 35 | 76 |
| `vision language model KV cache` | Semantic | 2 | 60 |

Both papers were retrievable in that later semantic index, unlike the original 4,878-paper collection. However, their ranks differed substantially depending on the wording of the query.

In particular, spelling out the phrase moved VL-Cache from rank 35 to rank 2. That is evidence of query sensitivity, not proof that the similarity implementation is incorrect.

A good evaluation should include abbreviations, expanded terms, exact names, and descriptive queries. We can then decide whether any general preprocessing change is justified. I would avoid adding a special expansion dictionary for one research topic just to improve those particular results.

## User

Should we combine the semantic search results and BM25 results? Since both search methods have their own advantages and disadvantages, maybe the results would be better if we use both of them.

## Codex

Hybrid search is a reasonable extension, but it introduces another ranking decision that we do not currently need for the core project.

BM25 and semantic scores are not directly comparable. Combining them would require a method such as reciprocal rank fusion or a calibrated scoring approach. We would also need to decide what to do when the two indexes cover different paper collections.

The original scope was to display one ranked list for the selected search mode, with BM25 as the default. Keeping that design makes it easier to understand which method produced the results and evaluate the two methods independently.

I would first make sure both search paths are correct, report their actual coverage, and compare their rankings using the same candidate collection. If hybrid retrieval is still useful after those checks, it can be documented as a future improvement instead of adding another required component.

## User

How should we check whether the search improvements actually work? I don't think just looking at the search results for one topic is enough.

## Codex

Agreed. I would use two levels of evaluation.

First, use a deterministic small corpus for implementation tests. It should contain papers with exact names, related terminology, partial keyword matches, and unrelated uses of common terms. This allows us to verify basic ranking behavior and catch regressions in tokenization, title matching, and paper-ID mapping.

Second, use a broader set of representative research queries for retrieval quality evaluation. For each query, record a set of known relevant papers and, where possible, judge additional returned papers consistently.

The evaluation should include topics outside VLM KV cache so that the improvements cannot be explained by tuning the implementation for a single topic.

Useful measurements are:

| Metric | What it tells us |
| --- | --- |
| Precision@10 | Fraction of the first ten results judged relevant |
| Recall@10 | Fraction of the known relevant set retrieved in the first ten results |
| Recall@50 | Whether a larger review list retrieves more of the known relevant set |
| MRR | How early the first judged-relevant result appears across queries |

If the relevance judgments are incomplete, describe recall relative to the known relevant set rather than claiming to measure all relevant papers that exist.

When comparing ranking algorithms, evaluate on a shared candidate corpus with a fixed set of queries and relevance judgments. We can separately evaluate the full deployed indexes to measure the practical effect of differences in coverage.

## User

I want to keep the evaluation relatively simple. Would it be sufficient to look at the top 10 results and see how many of the papers are actually related to the topic? That is probably what the user would care about when using the program.

## Codex

Yes. Precision@10 is a useful and understandable metric for the actual user experience.

I would define the relevance criteria before looking at the results. For example, for `VLM KV Cache`, a directly relevant paper would study KV cache management, compression, eviction, quantization, or a closely related efficiency problem in vision-language models. A paper that only mentions cache in an unrelated system would not count as directly relevant.

We can also record papers that are broadly related but do not directly address the requested research problem. That distinction is useful when interpreting borderline results.

An earlier qualitative check of the query reported that approximately nine of the top ten BM25 results were directly relevant, compared with five of the top ten semantic results. In that semantic run, the first three results included WindowQuant, VL-Cache, and LOOK-M.

That is a useful example of what a manual review can reveal. It was a particular check against a particular search state, not a final benchmark for all research queries. The subsequent rank observations also show that results can change across index generations or query formulations.

For a more defensible project evaluation, apply the same criteria to several topics, retain the returned paper IDs and ranks, and report the index versions used. Do not report an aggregate score unless those queries have actually been judged.

## User

It seems like even if the search method is working correctly, not all of the returned papers will be relevant. Is that expected? Should we only return papers if their score is higher than some threshold?

## Codex

Some irrelevant results are expected in a ranked retrieval system, especially for short or ambiguous research queries.

A top-k search returns the highest-ranked candidates that are available under its retrieval rules. It does not guarantee that every one of those candidates satisfies the user's interpretation of the topic.

A global score threshold can reduce the number of weak results, but it can also hide useful papers. BM25 scores depend on the query and corpus statistics, and a semantic similarity score is not automatically a calibrated probability of relevance.

I would not introduce an arbitrary threshold without evaluating it. For PaperSearch, the screening workflow already allows the user to mark results as relevant or irrelevant. A usable ranking that places relevant papers near the top is more important than pretending the application can make every screening decision automatically.

We should still avoid obviously misleading behavior. For example, a lexical query with no matching documents should not return unrelated documents simply to fill a page. Similarly, an unavailable semantic model should be treated as an execution problem rather than as evidence that the topic has no relevant papers.

## User

How should the application behave if the semantic model doesn't load or the semantic index isn't available? I want the program to still return papers instead of just failing.

## Codex

That should use the explicit BM25 fallback discussed in the code review.

If semantic execution is unavailable and the lexical index is usable, the API can run the equivalent BM25 query and communicate the requested mode, effective mode, and reason for the fallback. The Streamlit reviewer should display that information and reset pagination when appropriate.

A successful fallback should preserve the original query and applicable filters. It should not silently display BM25 results under a semantic-search label.

A valid semantic query with no results should remain distinct from an execution failure. We should not automatically fallback just because a query retrieves fewer relevant papers than we would like.

For evaluation, any run that uses fallback should be recorded as BM25, not counted as a successful semantic retrieval run.

## User

Can you summarize what we should actually change in the code and what should be tested? Please keep the fixes related to the existing program. I don't want to add another search engine or make it overly complicated.

## Codex

I would keep the existing components and make the smallest general changes supported by the observed problems.

### Lexical search

- Verify that the active index covers the intended collection rather than an unintended limited subset.
- Improve normalization and title or identifier matching where fixture tests demonstrate a problem.
- Check multi-term query behavior across different research areas.
- Preserve ordinary BM25 ranking and avoid topic-specific exceptions.

### Semantic search

- Check the selection of records for embedding generation and eliminate unintended sampling or date restrictions from the normal workflow.
- Maintain explicit coverage information and allow additional embeddings to be generated in batches.
- Verify compatible model settings, correct vector ordering, and the paper-ID and revision mapping.
- Preserve the explicit BM25 fallback for unavailable semantic execution.

### Validation

- Test exact-title, method-name, acronym, and descriptive topic queries.
- Verify that changes apply to other research areas, not just the known VLM papers.
- Run controlled ranking tests and a real-corpus relevance evaluation.
- Record lexical and semantic coverage, the index generation, and the effective search mode for each comparison.
- Keep the existing ingestion, screening, and Spark regression tests passing.

I would not add a vector database, a second search service, a reranking LLM, or a hybrid ranking system to address these problems. The observed issues can be investigated within the existing architecture.

## User

Do we still have the problem that semantic search only covers a very small number of papers? How do we know if PaperSearch actually returns useful results?

## Codex

The earlier code review reported artifacts containing approximately 3.05 million lexical records and 486,123 semantic vectors. That is a substantial increase from the early search indexes, but the two modes still have different coverage.

Those counts refer to the reviewed artifacts. They do not by themselves verify the current local application's loaded index or establish that every vector corresponds to an eligible current paper revision.

To answer that, I would verify the active index metadata and query the running API. The checks should distinguish coverage, execution correctness, and ranking quality:

- Coverage: confirm whether known relevant papers are represented in each active index.
- Execution: confirm that the requested mode actually produced the ranking and that the returned paper IDs match the underlying index entries.
- Quality: judge the first ten or fifty returned papers for representative research topics and compare the rankings with earlier results.

The recorded rank checks show that the expanded indexes could retrieve known VLM KV cache papers, while semantic ranking still varied with the wording of the query. That is a more useful conclusion than either claiming that semantic search is completely broken or claiming that all returned papers are relevant.

I would keep any additional changes proportional to the results of those checks. If the application is functioning reliably and the evaluation shows useful retrieval quality, there is no need to redesign the search system merely to add more techniques.

## User

That makes sense. I want to keep the search methods separate and make sure the general workflow works correctly. I don't want the project to become a much bigger information retrieval project when the main purpose is to demonstrate what I learned in CS544.

## Codex

Then I would keep the final search scope at BM25 and CPU-based semantic retrieval with explicit index coverage and a simple reviewer workflow.

The important lessons from the search problems are that the data pipeline determines which papers can be retrieved, the retrieval implementation determines their ranking, and the application needs to communicate the distinction between a valid ranking and an unavailable search mode.

We can retain the search fixtures and representative queries as regression tests. Any further implementation changes should be justified by concrete failures or measured improvements, rather than by adding more components.

The remaining project work is to verify these behaviors, ensure that the repository contains the necessary code and configuration, and confirm that it can reproduce the small-data workflow independently of the large generated artifacts.
