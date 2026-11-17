"""Real-model smoke test, explicitly enabled after the separate model download."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from lexmoryn.embedding import Encoder
from lexmoryn.index import build_index
from lexmoryn.search import SearchEngine


@pytest.fixture
def encoder(monkeypatch):
    directory = os.environ.get("LEXMORYN_TEST_MODEL")
    if not directory:
        pytest.skip("Set LEXMORYN_TEST_MODEL to run the downloaded, real multilingual encoder")

    def deny(*args, **kwargs):
        pytest.fail("Index/search must not use the network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    return Encoder(Path(directory))


def test_real_embeddings_normalization_retrieval_and_strict_ids(tmp_path, encoder):
    np = encoder.np
    vectors = encoder.encode(["Müşteriye para iadesi yapıldı.", "The telescope observes stars."])
    assert vectors.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    assert not np.allclose(vectors[0], vectors[1])
    (tmp_path / "refund.md").write_text("Müşteriye para iadesi yapıldı.\n")
    (tmp_path / "stars.md").write_text("The telescope observes stars.\n")
    (tmp_path / "v1.2.3.md").write_text("release v1.2.3\n")
    (tmp_path / "v1.2.30.md").write_text("release v1.2.30\n")
    build_index(tmp_path, encoder=encoder)
    engine = SearchEngine(tmp_path, encoder=encoder)
    assert engine.search("customer refund", "dense")["results"][0]["path"] == "refund.md"
    for mode in ("dense", "hybrid", "memory"):
        assert [r["path"] for r in engine.search("release v1.2.3", mode)["results"]] == [
            "v1.2.3.md"
        ]
        assert engine.search("release v9.9.9", mode)["results"] == []


def test_memory_expands_only_verified_evidence(encoder):
    root = Path(__file__).parents[1] / "examples/workspace"
    # The temporary index avoids writing anything to the fixture sources.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        index = Path(directory) / "index.sqlite3"
        build_index(root, index, encoder)
        engine = SearchEngine(root, index, encoder)
        response = engine.search("payment processing service", "memory")
        assert [claim["alias"] for claim in response["aliases_used"]] == ["Eagle"]
        assert "src/EagleService.cs" in [r["path"] for r in response["results"][:5]]
        assert engine.search("Falcon", "memory")["aliases_used"] == []
