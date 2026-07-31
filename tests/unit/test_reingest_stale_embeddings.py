"""Reproduction for issue #27: stale embeddings survive document re-ingestion.

https://github.com/jamjamgobambam/pathreview/issues/27

The ingestion pipeline appends embeddings via a raw ``vector_db.add(...)`` and never
deletes a source's prior vectors. Because ``source_id`` embeds a content hash, editing
a document produces a new source_id and its old vectors linger in the collection.
These tests drive the real re-ingestion path and assert the old version is purged.
The fix (``IngestionPipeline._purge_existing_vectors`` keyed on a stable
``base_source_id``) makes them pass; they now serve as regression tests.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from ingestion.pipeline import IngestionPipeline


class FakeCollection:
    """Minimal in-memory stand-in for a ChromaDB collection (add/get/delete)."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}  # id -> {embedding, metadata, document}

    def add(
        self,
        ids: list[str],
        embeddings: list | None = None,
        metadatas: list | None = None,
        documents: list | None = None,
    ) -> None:
        for i, _id in enumerate(ids):
            self.store[_id] = {
                "embedding": embeddings[i] if embeddings else None,
                "metadata": metadatas[i] if metadatas else {},
                "document": documents[i] if documents else "",
            }

    def get(self, where: dict | None = None, ids: list | None = None) -> dict[str, list]:
        matched = []
        for _id, rec in self.store.items():
            if ids and _id not in ids:
                continue
            if where:
                ((k, v),) = where.items()
                want = v.get("$eq", v) if isinstance(v, dict) else v
                if rec["metadata"].get(k) != want:
                    continue
            matched.append(_id)
        return {
            "ids": matched,
            "metadatas": [self.store[i]["metadata"] for i in matched],
            "documents": [self.store[i]["document"] for i in matched],
        }

    def delete(self, ids: list | None = None, where: dict | None = None) -> None:
        target = set(self.get(where=where, ids=ids)["ids"]) if (ids or where) else set(self.store)
        for _id in list(target):
            self.store.pop(_id, None)

    def all_source_ids(self) -> set:
        return {rec["metadata"].get("source_id") for rec in self.store.values()}


@pytest.fixture
def pipeline() -> tuple[IngestionPipeline, FakeCollection]:
    vector_db = FakeCollection()
    db_session = MagicMock()
    # _check_skip queries db_session; make it return None so re-ingestion proceeds.
    db_session.query.return_value.filter_by.return_value.first.return_value = None
    provider = MagicMock()
    provider.embed = lambda texts: [[0.1] * 8 for _ in texts]
    p = IngestionPipeline(
        vector_db=vector_db,
        db_session=db_session,
        embedding_provider=provider,
    )
    return p, vector_db


@pytest.mark.unit
def test_reingesting_edited_readme_purges_old_vectors(
    pipeline: tuple[IngestionPipeline, FakeCollection],
) -> None:
    """Editing and re-ingesting a document leaves only the current version's vectors."""
    p, vector_db = pipeline

    r1 = p.ingest_readme("profile-1", "repoX", "# Project\n\nInitial version of the docs.\n")
    r2 = p.ingest_readme("profile-1", "repoX", "# Project\n\nEdited version, content changed.\n")

    # Sanity: editing the content produced a new content-hashed source_id.
    assert r1.source_id != r2.source_id

    stored = vector_db.all_source_ids()
    assert r1.source_id not in stored, (
        f"Stale vectors from the previous README version {r1.source_id} "
        f"survived re-ingestion; store holds source_ids {stored}"
    )
    assert stored == {r2.source_id}


@pytest.mark.unit
def test_identical_reingest_keeps_single_version(
    pipeline: tuple[IngestionPipeline, FakeCollection],
) -> None:
    """Re-ingesting identical content re-writes the same ids without duplicating or erroring."""
    p, vector_db = pipeline
    content = "# Project\n\nUnchanged content ingested twice.\n"

    p.ingest_readme("profile-1", "repoX", content)
    ids_after_first = set(vector_db.store)
    p.ingest_readme("profile-1", "repoX", content)

    assert set(vector_db.store) == ids_after_first


@pytest.mark.unit
def test_first_time_ingest_purge_is_noop(
    pipeline: tuple[IngestionPipeline, FakeCollection],
) -> None:
    """The purge step is a safe no-op when the source has never been ingested before."""
    p, vector_db = pipeline

    result = p.ingest_readme("profile-1", "repoX", "# Project\n\nFirst ever ingest.\n")

    assert vector_db.all_source_ids() == {result.source_id}


@pytest.mark.unit
def test_reingest_scoped_to_repo_leaves_other_repo(
    pipeline: tuple[IngestionPipeline, FakeCollection],
) -> None:
    """Re-ingesting one repo's README must not delete another repo's vectors."""
    p, vector_db = pipeline

    repo_y = p.ingest_readme("profile-1", "repoY", "# Y\n\nRepo Y documentation.\n")
    p.ingest_readme("profile-1", "repoX", "# X\n\nRepo X documentation.\n")
    p.ingest_readme("profile-1", "repoX", "# X\n\nRepo X documentation, edited.\n")

    assert repo_y.source_id in vector_db.all_source_ids()


@pytest.mark.unit
def test_reingest_removes_all_old_chunks_multichunk(
    pipeline: tuple[IngestionPipeline, FakeCollection],
) -> None:
    """A multi-section document purges every old chunk, not just the first."""
    p, vector_db = pipeline
    v1 = "# Title\n\nIntro one.\n\n## Setup\n\nInstall one.\n\n## Usage\n\nRun one.\n"
    v2 = "# Title\n\nIntro two.\n\n## Setup\n\nInstall two.\n\n## Usage\n\nRun two.\n"

    r1 = p.ingest_readme("profile-1", "repoX", v1)
    r2 = p.ingest_readme("profile-1", "repoX", v2)

    stored = vector_db.all_source_ids()
    assert r1.source_id not in stored
    assert stored == {r2.source_id}
