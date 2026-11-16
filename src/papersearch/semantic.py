import sqlite3
from contextlib import closing
from threading import Lock

import numpy as np
import pyarrow.parquet as pq

from .encoder import DIM, RECIPE, Encoder


class SemanticReader:
    def __init__(self):
        self.lock = Lock()
        self.encoder = None
        self.path = None

    def search(self, folder, manifest, query, offset, limit):
        if not query.strip():
            raise ValueError("Enter a search query")
        if not manifest["coverage"]["semantic"] or manifest.get("recipe") != RECIPE:
            raise LookupError("This snapshot has no semantic index. Run the embedding worker and publish again.")
        path = folder / "semantic.parquet"
        with self.lock:
            if self.encoder is None:
                self.encoder = Encoder()
            if self.path != path:
                count = manifest["coverage"]["semantic"]
                ids = np.empty(count, dtype=np.int64)
                matrix = np.empty((count, DIM), dtype="<f4")
                start = 0
                with pq.ParquetFile(path) as file:
                    for batch in file.iter_batches(batch_size=256):
                        end = start + len(batch)
                        ids[start:end] = batch.column(0).to_numpy()
                        matrix[start:end] = np.frombuffer(b"".join(batch.column(1).to_pylist()), dtype="<f4").reshape(-1, DIM)
                        start = end
                if start != count:
                    raise ValueError("Semantic row count does not match the manifest")
                self.ids, self.matrix, self.path = ids, matrix, path
            vectors, lengths = self.encoder.encode([query], query=True)
            scores = self.matrix @ vectors[0]
            order = np.lexsort((self.ids, -scores))
            neighbors = [(int(self.ids[i]), float(scores[i])) for i in order[offset:offset + limit]]
        uri = (folder / "lexical.sqlite").resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as index:
            index.row_factory = sqlite3.Row
            hits = [
                dict(index.execute("SELECT paper_id,revision_id,title FROM documents WHERE rowid=?", (row,)).fetchone(),
                     rank=rank, score=score)
                for rank, (row, score) in enumerate(neighbors, offset + 1)
            ]
        return hits, offset + limit < len(order), lengths[0]
