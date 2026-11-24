import sqlite3
from contextlib import closing, nullcontext
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import HTTPException

from papersearch import semantic
from papersearch.encoder import DIM, RECIPE


@pytest.fixture
def search_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", "unused")
    from papersearch import api

    with closing(sqlite3.connect(tmp_path / "lexical.sqlite")) as db, db:
        db.execute(
            "CREATE VIRTUAL TABLE documents USING fts5(title,abstract,paper_id UNINDEXED,revision_id UNINDEXED)"
        )
        db.executemany(
            "INSERT INTO documents VALUES(?,?,?,?)",
            [("River models", "", "river", 10), ("Forest models", "", "forest", 20)],
        )
    vectors = np.eye(2, DIM, dtype="<f4")
    pq.write_table(
        pa.table(
            {"row_id": [1, 2], "value": [vector.tobytes() for vector in vectors]}
        ),
        tmp_path / "semantic.parquet",
    )
    manifest = {
        "snapshot_id": "test-snapshot",
        "coverage": {"lexical": 2, "semantic": 2},
        "recipe": RECIPE,
    }
    monkeypatch.setattr(api, "engine", SimpleNamespace(connect=nullcontext))
    monkeypatch.setattr(api, "check_project", lambda *_: None)
    monkeypatch.setattr(api, "active_snapshot", lambda *_: (1, tmp_path, manifest))
    monkeypatch.setattr(api, "semantic_reader", semantic.SemanticReader())

    def search(q="river", **kwargs):
        return api.search(uuid4(), q, **kwargs)

    return search, manifest, tmp_path, vectors


def test_semantic_search(search_snapshot, monkeypatch):
    search, _, _, vectors = search_snapshot
    encoder = SimpleNamespace(encode=lambda texts, *, query: (vectors[1:], [2]))
    monkeypatch.setattr(semantic, "Encoder", lambda: encoder)
    page = search(ranker="semantic", limit=1)
    assert page["requested_ranker"] == page["ranker"] == "semantic"
    assert page["fallback_reason"] is None
    assert page["results"][0]["revision_id"] == 20
    assert page["has_more"]


def test_bm25_fallback_with_zero_vectors(search_snapshot):
    search, manifest, _, _ = search_snapshot
    manifest["coverage"]["semantic"] = 0
    page = search(ranker="semantic")
    assert page["requested_ranker"] == "semantic"
    assert page["ranker"] == "bm25"
    assert page["fallback_reason"] == "The active snapshot has no semantic vectors"
    assert page["snapshot_id"] == manifest["snapshot_id"]
    assert page["results"] == search(ranker="bm25")["results"]


@pytest.mark.parametrize("missing", ["tokenizer.json", "model.onnx"])
def test_bm25_fallback_with_missing_model(search_snapshot, monkeypatch, missing):
    search, manifest, folder, _ = search_snapshot
    monkeypatch.setenv("PAPERSEARCH_MODEL_DIR", str(folder))
    if missing == "model.onnx":
        (folder / "tokenizer.json").touch()
    page = search(ranker="semantic", snapshot=manifest["snapshot_id"])
    assert page["requested_ranker"] == "semantic"
    assert page["ranker"] == "bm25"
    assert missing in page["fallback_reason"]
    assert page["results"][0]["revision_id"] == 10


def test_direct_bm25_search(search_snapshot, monkeypatch):
    search, _, _, _ = search_snapshot

    def unexpected_encoder():
        pytest.fail("BM25 should not load the semantic model")

    monkeypatch.setattr(semantic, "Encoder", unexpected_encoder)
    page = search(ranker="bm25", field="title")
    assert page["requested_ranker"] == page["ranker"] == "bm25"
    assert page["fallback_reason"] is None
    assert [hit["revision_id"] for hit in page["results"]] == [10]


def test_missing_semantic_index_is_an_error(search_snapshot, monkeypatch):
    search, _, folder, _ = search_snapshot
    monkeypatch.setattr(semantic, "Encoder", object)
    (folder / "semantic.parquet").unlink()
    with pytest.raises(HTTPException) as error:
        search(ranker="semantic")
    assert error.value.status_code == 503
    assert "semantic.parquet" in error.value.detail


@pytest.mark.parametrize("query", ["   ", "!!!"])
def test_invalid_query_is_an_error(search_snapshot, query):
    search, manifest, _, _ = search_snapshot
    manifest["coverage"]["semantic"] = 0
    with pytest.raises(HTTPException) as error:
        search(q=query, ranker="semantic")
    assert error.value.status_code == 422
