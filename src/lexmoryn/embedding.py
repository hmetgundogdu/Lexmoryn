"""Pinned off-the-shelf E5 ONNX encoder. Only download_model may access the network."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .text import digest

MODEL_REPO = "Xenova/multilingual-e5-small"
MODEL_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
MODEL_FILES = (
    "onnx/model_quantized.onnx",
    "tokenizer.json",
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
DEFAULT_MODEL_DIR = Path(".lexmoryn/models/multilingual-e5-small")


def model_identity() -> dict:
    return {
        "repo": MODEL_REPO,
        "revision": MODEL_REVISION,
        "weights": MODEL_FILES[0],
        "pooling": "masked-mean+l2",
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "max_tokens": 512,
    }


def download_model(directory: Path) -> dict:
    """Explicit, weights-only network step; workspace content is never an argument."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ValueError("Install semantic dependencies: uv sync --extra semantic") from exc
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        allow_patterns=list(MODEL_FILES),
        local_dir=directory,
    )
    manifest = {
        **model_identity(),
        "sha256": {name: digest((directory / name).read_bytes()) for name in MODEL_FILES},
    }
    (directory / "lexmoryn-model.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


class Encoder:
    def __init__(self, directory: Path = DEFAULT_MODEL_DIR, threads: int = 2):
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise ValueError("Install semantic dependencies: uv sync --extra semantic") from exc
        manifest_path = directory / "lexmoryn-model.json"
        if not manifest_path.is_file():
            raise ValueError(f"Model missing. Run lexmoryn download-model --model-dir {directory}")
        self.manifest = json.loads(manifest_path.read_text())
        if any(self.manifest.get(k) != v for k, v in model_identity().items()):
            raise ValueError("Model identity mismatch; download the pinned model again")
        for name in MODEL_FILES:
            if digest((directory / name).read_bytes()) != self.manifest["sha256"].get(name):
                raise ValueError(f"Model checksum mismatch: {name}")
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(directory / MODEL_FILES[0]), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {x.name for x in self.session.get_inputs()}

    def encode(self, texts: list[str], *, query: bool = False, batch_size: int = 8):
        np = self.np
        output = []
        prefix = "query: " if query else "passage: "
        for start in range(0, len(texts), batch_size):
            encoded = self.tokenizer.encode_batch(
                [prefix + t for t in texts[start : start + batch_size]]
            )
            inputs = {
                "input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64),
            }
            hidden = self.session.run(None, {k: v for k, v in inputs.items() if k in self.inputs})[
                0
            ]
            mask = inputs["attention_mask"][..., None]
            pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
            pooled /= np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
            output.extend(pooled.astype("<f4"))
        return np.asarray(output, dtype="<f4").reshape(-1, 384)
