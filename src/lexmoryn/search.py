"""Inspectable BM25, cosine search and reciprocal-rank fusion over the same chunks."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from contextlib import closing
from pathlib import Path, PurePosixPath

from .index import index_path, open_index
from .text import contains_literal, digest, strict_tokens, term_counts, tokens
from .workspace import MEMORY_FILE, file_hash, read_local

MODES = ("exact", "lexical", "dense", "hybrid", "memory")
RRF_K = 60


def literal_text(chunk: dict) -> str:
    path = PurePosixPath(chunk["path"])
    # Expose identifiers in filename stems without conflating near-identical IDs.
    return "\n".join([chunk["path"], path.stem, *path.stem.split("_"), chunk["text"]])


class SearchEngine:
    def __init__(self, root: Path, path: Path | None = None, encoder=None):
        self.root = root.resolve(strict=True)
        self.encoder = encoder
        with closing(open_index(self.root, index_path(self.root, path))) as db:
            self.meta = json.loads(db.execute("SELECT data FROM metadata").fetchone()[0])
            self.assets = {
                p: json.loads(data) for p, data in db.execute("SELECT path,data FROM assets")
            }
            rows = list(db.execute("SELECT data,vector FROM chunks ORDER BY rowid"))
            self.chunks = [json.loads(data) for data, _ in rows]
            self.relations = [json.loads(r[0]) for r in db.execute("SELECT data FROM relations")]
            self.aliases = [json.loads(r[0]) for r in db.execute("SELECT data FROM aliases")]
        self.matrix = None
        if encoder is not None:
            if encoder.manifest != self.meta["model"]:
                raise ValueError("Index/model mismatch; re-index with this model")
            np = encoder.np
            if any(vector is None for _, vector in rows):
                raise ValueError("Dense vectors missing; re-index with --semantic")
            self.matrix = np.asarray(
                [np.frombuffer(vector, dtype="<f4") for _, vector in rows], dtype="<f4"
            ).reshape(-1, 384)
        self.postings = defaultdict(dict)
        self.lengths = []
        for index, chunk in enumerate(self.chunks):
            counts = term_counts(chunk)
            self.lengths.append(sum(counts.values()))
            for term, count in counts.items():
                self.postings[term][index] = count
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))

    def _current(self, path: str, cache: dict) -> bool:
        if path not in cache:
            try:
                cache[path] = (
                    path in self.assets
                    and file_hash(self.root, path) == self.assets[path]["sha256"]
                )
            except (OSError, ValueError):
                cache[path] = False
        return cache[path]

    def memory(self, cache: dict | None = None) -> list[dict]:
        """Inspect claims with current validity, without mutating the stored snapshot."""
        cache = {} if cache is None else cache
        try:
            config_current = (
                digest(read_local(self.root, MEMORY_FILE)) == self.meta["alias_file_hash"]
            )
        except (OSError, ValueError):
            config_current = False
        claims = []
        for stored in self.aliases:
            row = dict(stored)
            evidence = row["evidence"]
            if not config_current:
                row.update(status="retracted", reason="alias_file_changed_reindex_required")
            elif row["status"] in {"verified", "inferred"} and (
                not self._current(evidence["path"], cache)
                or not all(self._current(target, cache) for target in row["targets"])
            ):
                row.update(status="retracted", reason="evidence_or_target_changed_reindex_required")
            claims.append(row)
        return claims

    def _memory(self, query: str, cache: dict) -> list[dict]:
        used = []
        for row in self.memory(cache):
            if row["status"] != "verified":
                continue
            phrases = (row["alias"], row["canonical"])
            if not any(
                re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", query, re.I) for p in phrases
            ):
                continue
            used.append(row)
        return used

    def related(self, path: str, cache: dict | None = None, limit: int = 10) -> list[dict]:
        cache = {} if cache is None else cache
        if not self._current(path, cache):
            return []
        return [
            edge
            for edge in self.relations
            if path in (edge["source"], edge["target"])
            and self._current(edge["source"], cache)
            and self._current(edge["target"], cache)
        ][:limit]

    def _lexical(self, query: str, eligible: set[int]) -> dict[int, float]:
        scores = defaultdict(float)
        total = len(self.chunks)
        for term in sorted(set(tokens(query))):
            posting = self.postings.get(term, {})
            idf = math.log(1 + (total - len(posting) + 0.5) / (len(posting) + 0.5))
            for index, frequency in posting.items():
                if index in eligible:
                    norm = 1.2 * (0.25 + 0.75 * self.lengths[index] / self.average_length)
                    scores[index] += idf * frequency * 2.2 / (frequency + norm)
        return dict(scores)

    def search(
        self,
        query: str,
        mode: str = "lexical",
        top_k: int = 10,
        strict_ids: bool = True,
        include_related: bool = True,
    ) -> dict:
        if mode not in MODES:
            raise ValueError(f"Unknown retrieval mode: {mode}")
        if top_k < 1 or not query.strip():
            raise ValueError("Search requires a nonempty query and positive top_k")
        if mode in {"dense", "hybrid", "memory"} and self.encoder is None:
            raise ValueError("This mode needs a semantic index and a local encoder")
        cache = {}
        required = strict_tokens(query) if strict_ids else []
        eligible = {
            i
            for i, chunk in enumerate(self.chunks)
            if all(contains_literal(literal_text(chunk), token) for token in required)
            and self._current(chunk["path"], cache)
        }
        used = self._memory(query, cache) if mode == "memory" else []
        expanded = query + "".join("\n" + r["alias"] + " " + r["canonical"] for r in used)
        components = {}
        if mode == "exact":
            components["exact"] = {
                i: 1.0
                for i in eligible
                if query in self.chunks[i]["path"] + "\n" + self.chunks[i]["text"]
            }
        if mode in {"lexical", "hybrid", "memory"}:
            components["lexical"] = self._lexical(expanded, eligible)
        if mode in {"dense", "hybrid", "memory"} and eligible:
            vector = self.encoder.encode([expanded], query=True)[0]
            scores = self.matrix @ vector
            components["dense"] = {i: float(scores[i]) for i in eligible}
        if used:
            targets = list(dict.fromkeys(t for row in used for t in row["targets"]))
            components["memory"] = {
                i: float(len(targets) - targets.index(c["path"]))
                for i, c in enumerate(self.chunks)
                if i in eligible and c["path"] in targets
            }
        scores = defaultdict(float)
        ranks = defaultdict(dict)
        for name, values in components.items():
            ordered = sorted(
                values,
                key=lambda i: (
                    -values[i],
                    self.chunks[i]["path"],
                    self.chunks[i]["start_line"] or 0,
                    i,
                ),
            )
            for rank, index in enumerate(ordered, 1):
                scores[index] += (
                    1 / (RRF_K + rank) if mode in {"hybrid", "memory"} else values[index]
                )
                ranks[index][name] = {"rank": rank, "score": values[index]}
        ordered = sorted(scores, key=lambda i: (-scores[i], self.chunks[i]["path"], i))
        results, seen = [], set()
        for index in ordered:
            chunk = self.chunks[index]
            if chunk["path"] in seen:
                continue
            seen.add(chunk["path"])
            row = {
                **chunk,
                "snippet": chunk["text"],
                "score": scores[index],
                "rank": len(results) + 1,
                "components": ranks[index],
                "sha256": self.assets[chunk["path"]]["sha256"],
                "content_status": self.assets[chunk["path"]]["status"],
            }
            del row["text"]
            if include_related:
                row["related"] = self.related(chunk["path"], cache)
            results.append(row)
            if len(results) == top_k:
                break
        return {
            "query": query,
            "mode": mode,
            "workspace_id": self.meta["workspace_id"],
            "strict_tokens": required,
            "aliases_used": used,
            "results": results,
            "stale_files_skipped": sorted(p for p, valid in cache.items() if not valid),
        }
