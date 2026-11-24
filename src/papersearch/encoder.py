import os
import zlib
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
RECIPE = f"{MODEL}:{REVISION}:title-lf-abstract-cls128-v1"
DIM = 384
MAX_TOKENS = 128
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def eligible(paper, payload):
    if paper.startswith("fixture:"):
        return True
    recent = (payload["published"] or "") >= "2024-01-01"
    cs_or_ml = any(
        category.startswith("cs.") or category == "stat.ML"
        for category in payload["categories"]
    )
    return (recent and cs_or_ml) or zlib.crc32(paper.encode("utf-8")) % 100 < 5


def passage(title, abstract):
    return title + "\n" + abstract if abstract else title


class MissingModelFile(FileNotFoundError):
    pass


class Encoder:
    def __init__(self, directory=None, threads=2):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(
            directory
            or os.environ.get(
                "PAPERSEARCH_MODEL_DIR",
                str(
                    Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
                    / "models"
                    / "bge-small-en-v1.5"
                ),
            )
        )
        for name in ("tokenizer.json", "model.onnx"):
            if not (directory / name).is_file():
                raise MissingModelFile(f"Missing BGE model file: {directory / name}")
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        if not 1 <= threads <= 8:
            raise ValueError("Expected 1–8 CPU threads")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.np = np

    def encode(self, texts, *, query=False):
        np = self.np
        if not 1 <= len(texts) <= 64:
            raise ValueError("Expected 1–64 texts")
        tokens = self.tokenizer.encode_batch(
            [QUERY_PREFIX + t if query else t for t in texts]
        )
        lengths = [len(t.ids) for t in tokens]
        width = min(max(lengths), MAX_TOKENS)
        ids = np.zeros((len(tokens), width), dtype=np.int64)
        mask = np.zeros_like(ids)
        for i, t in enumerate(tokens):
            row = t.ids
            if len(row) > width:
                row = row[: width - 1] + row[-1:]  # Preserve the final SEP.
            ids[i, : len(row)] = row
            mask[i, : len(row)] = 1
        (hidden,) = self.session.run(
            ["last_hidden_state"],
            dict(input_ids=ids, attention_mask=mask, token_type_ids=np.zeros_like(ids)),
        )
        cls = hidden[:, 0, :]
        vectors = (cls / np.linalg.norm(cls, axis=1, keepdims=True)).astype("<f4")
        if vectors.shape != (len(texts), DIM) or not np.isfinite(vectors).all():
            raise ValueError("Invalid model output")
        return vectors, lengths
