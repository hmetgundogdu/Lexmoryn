"""Atomic full-rescan SQLite snapshots. No workspace source file is modified."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from .text import digest
from .workspace import MAX_BYTES, aliases, discover, relations

SCHEMA_VERSION = 1


def index_path(root: Path, explicit: Path | None = None) -> Path:
    return explicit.absolute() if explicit else root / ".lexmoryn/index.sqlite3"


def open_index(root: Path, path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"Index not found: {path}. Run lexmoryn index first")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        meta = json.loads(connection.execute("SELECT data FROM metadata").fetchone()[0])
        if meta["schema_version"] != SCHEMA_VERSION or meta["root"] != str(root):
            raise ValueError("Index schema or workspace mismatch; rebuild this workspace's index")
    except BaseException:
        connection.close()
        raise
    return connection


def build_index(root: Path, path: Path | None = None, encoder=None) -> dict:
    started = time.perf_counter()
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    destination = index_path(root, path)
    if destination.is_file():
        with closing(open_index(root, destination)):
            pass
    # Never let an explicitly located index become part of the corpus.
    excluded = {
        destination,
        destination.with_name(destination.name + "-wal"),
        destination.with_name(destination.name + "-shm"),
    }
    assets, chunks, texts, diagnostics = discover(root, excluded)
    links = relations(texts, assets)
    memory, memory_hash = aliases(root, texts, assets)
    extraction_seconds = time.perf_counter() - started
    vectors = None
    if encoder is not None:
        vectors = encoder.encode(
            [c["path"] + "\n" + " ".join(c["symbols"]) + "\n" + c["text"] for c in chunks]
        )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "workspace_id": digest(str(root).encode()),
        "extractor": "utf8-character-windows-v1",
        "max_bytes": MAX_BYTES,
        "max_chunk_chars": 1200,
        "overlap_chars": 160,
        "model": encoder.manifest if encoder is not None else None,
        "alias_file_hash": memory_hash,
        "corpus_hash": digest(json.dumps([(a["path"], a["sha256"]) for a in assets]).encode()),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".lexmoryn-index-", dir=destination.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript("""
                CREATE TABLE metadata (data TEXT NOT NULL);
                CREATE TABLE assets (path TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE chunks (id TEXT PRIMARY KEY, data TEXT NOT NULL, vector BLOB);
                CREATE TABLE relations (data TEXT NOT NULL);
                CREATE TABLE aliases (data TEXT NOT NULL);
            """)
            db.execute("INSERT INTO metadata VALUES (?)", (json.dumps(metadata),))
            db.executemany(
                "INSERT INTO assets VALUES (?, ?)", [(a["path"], json.dumps(a)) for a in assets]
            )
            db.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?)",
                [
                    (c["id"], json.dumps(c), vectors[i].tobytes() if vectors is not None else None)
                    for i, c in enumerate(chunks)
                ],
            )
            for table, rows in (("relations", links), ("aliases", memory)):
                db.executemany(f"INSERT INTO {table} VALUES (?)", [(json.dumps(r),) for r in rows])
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "files": len(assets),
        "chunks": len(chunks),
        "relations": len(links),
        "aliases": memory,
        "diagnostics": diagnostics,
        "extraction_seconds": extraction_seconds,
        "index_seconds": time.perf_counter() - started,
        "index_bytes": destination.stat().st_size,
        "corpus_hash": metadata["corpus_hash"],
        "alias_file_hash": memory_hash,
        "model": metadata["model"],
    }
