# AI-generated code (Codex): bounded physical-line reader.
from papersearch import stream


def test_reader_resumes_after_oversized_line(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "MAX_LINE_BYTES", 8)
    source = tmp_path / "input.jsonl"
    source.write_bytes(b"0123456789\nvalid\nlast")
    assert list(stream.raw_lines(source)) == [(1, None), (2, b"valid\n"), (3, b"last")]
