# AI-generated code (Codex): canonical record normalization.
import json

import pytest

from papersearch.records import RecordError, parse_record, revision_values


def fixture(**changes):
    return json.dumps(
        {
            "id": "river",
            "source_version": 1,
            "source_updated_at": "2025-01-01T00:00:00Z",
            "title": "A river",
            "abstract": "Two streams.",
            "categories": ["cs.LG", "cs.AI"],
            **changes,
        }
    ).encode()


def test_normalization_is_exact_and_order_independent():
    a = parse_record(fixture(), "fixture")
    b = parse_record(
        fixture(title=" A   river ", categories=["cs.AI", "cs.LG", "cs.AI"]), "fixture"
    )
    assert revision_values(a) == revision_values(b)
    assert revision_values(a) != revision_values(
        parse_record(fixture(title="A River"), "fixture")
    )


def test_arxiv_uses_version_history_and_submission_date():
    row = {
        "id": "2401.00001",
        "title": "A paper",
        "categories": "cs.LG stat.ML",
        "versions": [
            {"version": "v1", "created": "Mon, 1 Jan 2024 01:00:00 GMT"},
            {"version": "v2", "created": "Tue, 2 Jan 2024 02:00:00 GMT"},
        ],
        "update_date": "2024-01-03",
    }
    revision = parse_record(json.dumps(row).encode(), "arxiv")
    assert revision.paper_id == "arxiv:2401.00001"
    assert (
        revision.version_rank,
        revision.source_updated_at,
        revision.payload.published,
    ) == (
        2,
        "2024-01-03T00:00:00.000000Z",
        "2024-01-01",
    )


def test_invalid_record():
    with pytest.raises(RecordError, match="invalid_paper_id"):
        parse_record(fixture(id="bad id"), "fixture")
