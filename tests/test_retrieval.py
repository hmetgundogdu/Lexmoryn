from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from lexmoryn.cli import main
from lexmoryn.index import build_index
from lexmoryn.search import SearchEngine
from lexmoryn.text import chunks, contains_literal, strict_tokens


def put(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def setup_alias(root: Path, *, status: str = "verified") -> dict:
    put(root, "src/Eagle.cs", "public class Eagle { }\n")
    quote = "Eagle is the payment processing service in src/Eagle.cs."
    put(root, "docs/design.md", "# Design\n" + quote + "\n")
    claim = {
        "alias": "Eagle",
        "canonical": "payment processing service",
        "targets": ["src/Eagle.cs"],
        "status": status,
        "evidence": {"path": "docs/design.md", "start_line": 2, "end_line": 2, "quote": quote},
    }
    put(root, ".lexmoryn-aliases.json", json.dumps({"version": 1, "aliases": [claim]}))
    return claim


def test_names_contents_symbols_metadata_and_exact_locations(tmp_path):
    put(tmp_path, "src/service.py", 'class Sensor:\n    """Persist pressure measurements."""\n')
    put(tmp_path, "binary/thermal_inspection.png", "secret content is unsupported")
    put(tmp_path, "broken.json", "\0not text")
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    hit = engine.search("pressure measurements")["results"][0]
    assert hit["path"] == "src/service.py"
    assert hit["symbols"] == ["Sensor"]
    assert (hit["start_line"], hit["end_line"]) == (1, 2)
    assert hit["snippet"] == (tmp_path / hit["path"]).read_text()
    image = engine.search("thermal inspection")["results"][0]
    assert image["path"].endswith(".png") and image["start_line"] is None
    assert engine.search("secret content")["results"] == []
    assert engine.assets["broken.json"]["status"] == "binary_content"


def test_search_locates_a_specific_passage_in_a_long_file(tmp_path):
    lines = [f"Unrelated garden note {i}.\n" for i in range(600)]
    lines[274] = "Zirconium pressure resonance is measured by the coolant sensor.\n"
    put(tmp_path, "manual.md", "".join(lines))
    report = build_index(tmp_path)
    response = SearchEngine(tmp_path).search("zirconium pressure resonance")
    assert report["chunks"] > 5
    assert len(response["results"]) == 1
    hit = response["results"][0]
    assert hit["start_line"] <= 275 <= hit["end_line"]
    assert lines[274] in hit["snippet"]


def test_ignore_rules_symlinks_and_hidden_state(tmp_path):
    put(tmp_path, ".gitignore", "*.txt\n!keep.txt\nignored/\n")
    put(tmp_path, "keep.txt", "visible")
    put(tmp_path, "skip.txt", "hidden")
    put(tmp_path, "nested/.gitignore", "!restored.txt\n")
    put(tmp_path, "nested/restored.txt", "restored")
    put(tmp_path, "ignored/secret.md", "secret")
    put(tmp_path, ".env", "credentials")
    put(tmp_path, ".lexmoryn/old.txt", "old index data")
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    report = build_index(tmp_path)
    assert set(SearchEngine(tmp_path).assets) == {"keep.txt", "nested/restored.txt"}
    assert {"path": "escape", "reason": "symlink_skipped"} in report["diagnostics"]


def test_import_and_markdown_relations_are_literal_and_retract_when_stale(tmp_path):
    put(tmp_path, "src/ledger.py", "class Ledger: pass\n")
    put(tmp_path, "src/settle.py", "from .ledger import Ledger\n")
    put(tmp_path, "web/client.ts", "export const client = 1;\n")
    put(tmp_path, "web/page.ts", "import { client } from './client';\n")
    put(tmp_path, "docs/readme.md", "[ledger](../src/ledger.py) [outside](../../outside.txt)\n")
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    edges = engine.related("src/ledger.py")
    assert {(e["source"], e["kind"]) for e in edges} == {
        ("src/settle.py", "import"),
        ("docs/readme.md", "markdown_link"),
    }
    assert engine.related("web/page.ts")[0]["target"] == "web/client.ts"
    assert all(e["evidence"]["start_line"] == 1 for e in edges)
    (tmp_path / "src/ledger.py").unlink()
    assert engine.related("src/ledger.py") == []
    assert engine.related("src/settle.py") == []


def test_full_rescan_stable_ids_modification_deletion_and_rename(tmp_path):
    put(tmp_path, "a.txt", "alpha")
    put(tmp_path, "b.txt", "bravo")
    initial = build_index(tmp_path)
    before = SearchEngine(tmp_path)
    build_index(tmp_path)
    assert before.chunks == SearchEngine(tmp_path).chunks
    put(tmp_path, "a.txt", "changed")
    (tmp_path / "b.txt").rename(tmp_path / "renamed.txt")
    report = build_index(tmp_path)
    after = SearchEngine(tmp_path)
    assert initial["corpus_hash"] != report["corpus_hash"]
    assert set(after.assets) == {"a.txt", "renamed.txt"}
    assert after.search("alpha")["results"] == []
    assert after.search("bravo")["results"][0]["path"] == "renamed.txt"
    (tmp_path / "a.txt").unlink()
    build_index(tmp_path)
    assert set(SearchEngine(tmp_path).assets) == {"renamed.txt"}


def test_stale_search_and_symlink_substitution_are_suppressed(tmp_path):
    put(tmp_path, "a.txt", "indexed secret")
    put(tmp_path, "b.txt", "indexed other")
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    put(tmp_path, "a.txt", "changed contents")
    (tmp_path / "b.txt").unlink()
    (tmp_path / "b.txt").symlink_to(tmp_path / "a.txt")
    response = engine.search("indexed")
    assert not response["results"]
    assert response["stale_files_skipped"] == ["a.txt", "b.txt"]


def test_alias_evidence_scope_conflict_and_conjectures(tmp_path):
    claim = setup_alias(tmp_path)
    report = build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    assert report["aliases"][0]["status"] == "verified"
    assert engine._memory("Eagle", {})[0]["canonical"] == "payment processing service"
    assert engine._memory("payment processing service", {})
    assert engine._memory("Eaglet", {}) == []
    # A changed source immediately invalidates memory, even before rebuilding the index.
    put(tmp_path, "docs/design.md", "No documented alias now.\n")
    assert engine._memory("Eagle", {}) == []
    assert engine.memory()[0]["status"] == "retracted"
    assert build_index(tmp_path)["aliases"][0]["status"] == "retracted"
    setup_alias(tmp_path, status="inferred")
    build_index(tmp_path)
    assert SearchEngine(tmp_path)._memory("Eagle", {}) == []
    setup_alias(tmp_path)
    second = {
        **claim,
        "canonical": "bird observation service",
        "evidence": {
            "path": "docs/other.md",
            "start_line": 1,
            "end_line": 1,
            "quote": "Eagle is the bird observation service in src/Eagle.cs.",
        },
    }
    put(tmp_path, "docs/other.md", second["evidence"]["quote"])
    put(tmp_path, ".lexmoryn-aliases.json", json.dumps({"version": 1, "aliases": [claim, second]}))
    assert {a["status"] for a in build_index(tmp_path)["aliases"]} == {"conflicted"}
    assert SearchEngine(tmp_path)._memory("Eagle", {}) == []


def test_alias_file_changes_and_failed_index_are_atomic(tmp_path):
    setup_alias(tmp_path)
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    before = (tmp_path / ".lexmoryn/index.sqlite3").read_bytes()
    put(tmp_path, ".lexmoryn-aliases.json", "{}")
    assert engine._memory("Eagle", {}) == []
    with pytest.raises(ValueError, match="version"):
        build_index(tmp_path)
    assert (tmp_path / ".lexmoryn/index.sqlite3").read_bytes() == before


def test_workspace_index_cannot_be_reused_in_another_root(tmp_path):
    a, b = tmp_path / "one", tmp_path / "two"
    a.mkdir()
    b.mkdir()
    setup_alias(a)
    put(b, "Eagle.txt", "Eagle is a bird")
    build_index(a)
    with pytest.raises(ValueError, match="workspace mismatch"):
        SearchEngine(b, a / ".lexmoryn/index.sqlite3")
    with pytest.raises(ValueError, match="workspace mismatch"):
        build_index(b, a / ".lexmoryn/index.sqlite3")


@pytest.mark.parametrize(
    "query,expected",
    [
        ("release v1.2.3", "v1.2.3.md"),
        ("invoice INV-2048", "invoice.md"),
        ("hash deadbeefcafebabe", "checksum.md"),
    ],
)
def test_strict_tokens_survive_lexical_and_exact_search(tmp_path, query, expected):
    put(tmp_path, "v1.2.3.md", "release v1.2.3")
    put(tmp_path, "v1.2.30.md", "release v1.2.30")
    put(tmp_path, "rc.md", "release v1.2.3-rc1")
    put(tmp_path, "invoice.md", "invoice INV-2048")
    put(tmp_path, "invoice-other.md", "invoice INV-2049")
    put(tmp_path, "checksum.md", "hash deadbeefcafebabe")
    put(tmp_path, "checksum-other.md", "hash deadbeefcafebabf")
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    assert [r["path"] for r in engine.search(query)["results"]] == [expected]
    assert [r["path"] for r in engine.search(query, "exact")["results"]] == [expected]
    assert not engine.search("release v9.9.9")["results"]


def test_strict_ids_in_filename_only_and_case_sensitive(tmp_path):
    put(tmp_path, "v1.2.3.bin", "binary")
    put(tmp_path, "v1.2.30.bin", "binary")
    build_index(tmp_path)
    engine = SearchEngine(tmp_path)
    assert [r["path"] for r in engine.search("v1.2.3")["results"]] == ["v1.2.3.bin"]
    assert not engine.search("V1.2.3")["results"]
    assert len(engine.search("v1.2.3", strict_ids=False)["results"]) == 2


def test_unicode_long_lines_and_overlapping_chunks_have_exact_locators():
    text = "# Başlık 🌍\n" + "温度 çok sıcak 🌡️ " * 300 + "\nneedle\n" + "other\n" * 400
    extracted = chunks("文档/ölçüm.md", text, ".md")
    assert len(extracted) > 5
    lines = text.splitlines(keepends=True)
    coverage = set()
    for chunk in extracted:
        start = sum(map(len, lines[: chunk["start_line"] - 1])) + chunk["start_column"] - 1
        end = sum(map(len, lines[: chunk["end_line"] - 1])) + chunk["end_column"] - 1
        assert text[start:end] == chunk["text"]
        assert len(chunk["text"]) <= 1200
        coverage.update(range(start, end))
    assert coverage == set(range(len(text)))
    assert strict_tokens("v1.2.3 INV-2048 deadbeefcafebabe") == [
        "v1.2.3",
        "INV-2048",
        "deadbeefcafebabe",
    ]
    assert not contains_literal("v1.2.30", "v1.2.3")


@pytest.mark.parametrize(
    "source",
    [
        "Release v1.2.3.",
        "image:registry/demo:v1.2.3",
        "releases/v1.2.3/notes.md",
        "Version: v1.2.3, accepted",
        "releases/stable-v1.2.3/notes.md",
    ],
)
def test_strict_id_boundaries_allow_sentence_punctuation_labels_and_paths(source):
    assert contains_literal(source, "v1.2.3")


@pytest.mark.parametrize(
    "source",
    [
        "v1.2.30",
        "v1.2.3-rc1",
        "v1.2.3.4",
        "prefixv1.2.3",
        "v1.2.3suffix",
    ],
)
def test_strict_id_boundaries_reject_longer_identifiers(source):
    assert not contains_literal(source, "v1.2.3")


def test_lexical_cli_never_connects_or_executes_workspace_code(tmp_path, monkeypatch, capsys):
    def deny(*args, **kwargs):
        pytest.fail("Unexpected network connection")

    monkeypatch.setattr(socket.socket, "connect", deny)
    put(tmp_path, "unsafe.py", "raise RuntimeError('Do not execute me')\nclass Evidence: pass\n")
    assert main(["index", str(tmp_path)]) == 0
    assert main(["search", str(tmp_path), "Evidence"]) == 0
    assert '"path": "unsafe.py"' in capsys.readouterr().out


def test_index_database_is_read_only_during_search(tmp_path):
    put(tmp_path, "a.md", "example")
    build_index(tmp_path)
    before = (tmp_path / ".lexmoryn/index.sqlite3").read_bytes()
    SearchEngine(tmp_path).search("example")
    assert before == (tmp_path / ".lexmoryn/index.sqlite3").read_bytes()
    with sqlite3.connect(tmp_path / ".lexmoryn/index.sqlite3") as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
