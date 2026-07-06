# PathReview — Module 3 Journal

## Week 7 — Issue selection

**Issue link:** https://github.com/jamjamgobambam/pathreview/issues/27

**Issue title:** Vector store returns stale embeddings after a document is re-ingested

**Tier:** [ ] Tier 1  [ ] Tier 2  [x] Tier 3

**Problem summary:**
PathReview ingests a user's documents (README, resume, repo files), splits them
into chunks, embeds them, and stores the vectors in a ChromaDB collection that the
RAG retriever later searches. The bug is in how the system handles re-ingestion.
When embeddings are written, the ingestion pipeline makes a raw `vector_db.add(...)`
call, which appends rather than replaces. There is a `VectorStore.delete_by_source_id()`
method meant to clean up a document's old vectors, but nothing in the codebase ever
calls it. This is made worse by how chunk IDs are assigned: each chunk's `source_id`
comes from a content hash, so editing a document and re-ingesting it produces a
brand-new `source_id`. The old vectors are never overwritten, and they linger in the
collection as stale results that retrieval can still return and feed into the
generated review.

A correct fix wires cleanup into the re-ingestion path, either deleting a source's
prior vectors before adding the new ones or upserting with stable IDs, so that after
a document is re-ingested the store holds exactly one current set of chunks. The
change touches the RAG retriever (`rag/retriever/vector_store.py`) and the ingestion
pipeline (`ingestion/pipeline.py`, `ingestion/embeddings/batch_processor.py`), which
is what makes this a whole-pipeline (Tier 3) change rather than a localized fix.

**Selection notes — "Is this right for me?" checklist:**
- Tier 3 fit: I work as a junior full-stack engineer and have contributed to large
  codebases, so per the checklist ("if I've contributed to large codebases before,
  Tier 2 or 3 is fair game") Tier 3 is appropriate. This issue requires
  understanding how ingestion, embedding storage, and RAG retrieval interact —
  multiple modules and the AI pipeline — which matches the Tier 3 definition.
- I can explain the problem in my own words without re-reading the issue (above).
- I located the exact code: `delete_by_source_id` in
  `rag/retriever/vector_store.py` (and confirmed via grep that it is never called),
  the append-only `vector_db.add(...)` in
  `ingestion/embeddings/batch_processor.py`, and the content-hash `source_id` built
  in `ingestion/pipeline.py`. I read each end to end.
- Concrete before/after: before, re-ingesting an edited document leaves its old
  vectors in the store, so stale chunks can be retrieved and fed into the review;
  after, only the current set of chunks for that source remains.
- Test plan exists: `tests/unit/test_batch_processor.py` already mocks a
  `vector_db`; I can extend it (or add `tests/unit/test_vector_store.py`) to ingest
  content, re-ingest an edited version, and assert the old chunk IDs are gone —
  deterministic with an in-memory fake.
- Scope/time: estimated ~6–9 hours across Weeks 8–9, achievable before the
  deadline. Not claimed (0 comments, not in the ledger), no blockers or
  dependencies.

**Branch name:** fix/27-stale-embeddings-reingest

**Setup confirmation:** [x] App runs locally at localhost:5173

**Cohort ledger:** [x] Issue added to cohort ledger
