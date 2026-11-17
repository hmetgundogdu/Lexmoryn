"""Reproducible per-mode subprocess measurements; no fabricated/human-label claims."""

from __future__ import annotations

import json
import math
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .embedding import Encoder
from .index import build_index
from .search import SearchEngine
from .text import contains_literal, digest
from .workspace import local_path, read_local


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def relevance_metrics(paths: list[str], relevant: list[dict]) -> dict:
    gold = {row["path"] for row in relevant}
    return {
        "recall_at_5": len(gold.intersection(paths[:5])) / len(gold),
        "recall_at_10": len(gold.intersection(paths[:10])) / len(gold),
        "mrr_at_10": next((1 / rank for rank, path in enumerate(paths[:10], 1) if path in gold), 0),
    }


def load_queries(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError("Query file must have a queries list and judgment provenance")
    queries = payload["queries"]
    if not queries or not payload.get("judgment_provenance"):
        raise ValueError("Need queries and explicit judgment_provenance")
    seen = set()
    for row in queries:
        if not isinstance(row, dict):
            raise ValueError("Queries must be objects")
        if (
            not isinstance(row.get("id"), str)
            or row["id"] in seen
            or not isinstance(row.get("query"), str)
            or not row["query"].strip()
            or not isinstance(row.get("relevant"), list)
            or not row["relevant"]
            or not isinstance(row.get("category"), str)
        ):
            raise ValueError("Each query needs a unique id, text and nonempty relevant judgments")
        seen.add(row["id"])
        for gold in row["relevant"]:
            if not isinstance(gold, dict) or not isinstance(gold.get("path"), str):
                raise ValueError("Each relevance judgment needs a path")
            first, last = gold.get("start_line"), gold.get("end_line")
            if (
                (first is None) != (last is None)
                or first is not None
                and (type(first) is not int or type(last) is not int or not 1 <= first <= last)
            ):
                raise ValueError("Judged evidence needs valid line ranges or null")
    return payload


def _worker(spec: dict) -> dict:
    root = Path(spec["workspace"])
    mode = spec["mode"]
    started = time.perf_counter()
    encoder = None if mode == "lexical" else Encoder(Path(spec["model_dir"]), spec["threads"])
    model_seconds = time.perf_counter() - started
    report = build_index(root, Path(spec["index"]), encoder)
    started = time.perf_counter()
    engine = SearchEngine(root, Path(spec["index"]), encoder)
    engine_seconds = time.perf_counter() - started
    details, latencies = [], []
    locations, correct_locations, judged, correct_judged = 0, 0, 0, 0
    id_results, false_ids = 0, 0
    for row in spec["queries"]:
        # A warm-up per query is excluded; timed repetitions include query encoding, hashing,
        # ranking, exact filtering, alias verification and related-edge verification.
        response = engine.search(row["query"], mode)
        for _ in range(spec["repeats"]):
            started = time.perf_counter()
            response = engine.search(row["query"], mode)
            latencies.append((time.perf_counter() - started) * 1000)
        results = response["results"]
        metric = relevance_metrics([r["path"] for r in results], row["relevant"])
        gold_by_path = {gold["path"]: gold for gold in row["relevant"]}
        for result in results:
            if result["start_line"] is not None:
                locations += 1
                text = read_local(root, result["path"]).decode("utf-8")
                lines = text.splitlines(keepends=True)
                first, last = result["start_line"], result["end_line"]
                span = "".join(lines[first - 1 : last])
                # Verify exact columns too, including windows cut within a long line.
                offset = sum(len(line) for line in lines[: first - 1]) + result["start_column"] - 1
                end_offset = sum(len(line) for line in lines[: last - 1]) + result["end_column"] - 1
                correct_locations += (
                    1 <= first <= last <= len(lines)
                    and result["snippet"] in span
                    and text[offset:end_offset] == result["snippet"]
                )
                gold = gold_by_path.get(result["path"])
                if gold and gold.get("start_line") is not None:
                    judged += 1
                    correct_judged += first <= gold["end_line"] and last >= gold["start_line"]
            if response["strict_tokens"]:
                id_results += 1
                # Independent whole-asset check, not only the retrieval chunk.
                asset_text = result["path"] + "\n" + Path(result["path"]).stem
                if result["content_status"] == "text":
                    asset_text += "\n" + read_local(root, result["path"]).decode("utf-8")
                false_ids += not all(
                    contains_literal(asset_text, token) for token in response["strict_tokens"]
                )
        details.append(
            {
                "id": row["id"],
                "query": row["query"],
                "category": row["category"],
                **metric,
                "ranked_paths": [r["path"] for r in results],
                "top_evidence": [
                    {k: r[k] for k in ("path", "start_line", "end_line")} for r in results[:3]
                ],
                "aliases_used": [r["alias"] for r in response["aliases_used"]],
            }
        )
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mib = peak / (1024 * 1024 if sys.platform == "darwin" else 1024)
    return {
        "mode": mode,
        **{
            key: statistics.mean(row[key] for row in details)
            for key in ("recall_at_5", "recall_at_10", "mrr_at_10")
        },
        "p50_latency_ms": statistics.median(latencies),
        "p95_latency_ms": percentile(latencies, 0.95),
        "timed_searches": len(latencies),
        "index_seconds": report["index_seconds"],
        "model_load_seconds": model_seconds,
        "engine_load_seconds": engine_seconds,
        "peak_rss_mib": peak_mib,
        "index_bytes": report["index_bytes"],
        "files": report["files"],
        "chunks": report["chunks"],
        "relations": report["relations"],
        "corpus_hash": report["corpus_hash"],
        "alias_file_hash": report["alias_file_hash"],
        "model": report["model"],
        "exact_id_false_positives": false_ids,
        "exact_id_results": id_results,
        "source_locations_correct": correct_locations,
        "source_locations_checked": locations,
        "judged_passage_overlaps": correct_judged,
        "judged_passages_retrieved": judged,
        "queries": details,
    }


def evaluate(
    workspace: Path,
    queries: Path,
    output: Path,
    model_dir: Path,
    repeats: int = 3,
    threads: int = 2,
    lexical_only: bool = False,
    index: Path | None = None,
) -> dict:
    if index is not None:
        raise ValueError("Evaluation uses isolated temporary indexes; omit --index")
    if repeats < 1 or threads < 1:
        raise ValueError("repeats and threads must be positive")
    query_file_hash = digest(queries.read_bytes())
    payload = load_queries(queries)
    workspace = workspace.resolve(strict=True)
    for row in payload["queries"]:
        for gold in row["relevant"]:
            if not local_path(workspace, gold["path"]).is_file():
                raise ValueError(f"Judged file missing: {gold['path']}")
            if gold.get("start_line") is not None:
                text = read_local(workspace, gold["path"]).decode("utf-8")
                if gold["end_line"] > len(text.splitlines()):
                    raise ValueError(f"Judged lines out of range: {gold['path']}")
    modes = ["lexical"] if lexical_only else ["lexical", "dense", "hybrid", "memory"]
    results = []
    with tempfile.TemporaryDirectory(prefix="lexmoryn-evaluation-") as temporary:
        for mode in modes:
            print(f"Measuring {mode} in a fresh process...", file=sys.stderr, flush=True)
            spec = {
                "workspace": str(workspace.resolve()),
                "queries": payload["queries"],
                "model_dir": str(model_dir.resolve()),
                "mode": mode,
                "repeats": repeats,
                "threads": threads,
                "index": str(Path(temporary) / f"{mode}.sqlite3"),
            }
            process = subprocess.run(
                [sys.executable, "-m", "lexmoryn.evaluation", "--worker"],
                input=json.dumps(spec),
                text=True,
                capture_output=True,
            )
            if process.returncode:
                raise ValueError(f"Evaluation {mode} failed:\n{process.stderr}")
            results.append(json.loads(process.stdout))
    if len({row["corpus_hash"] for row in results}) != 1:
        raise ValueError("Corpus changed between modes; discard run and retry")
    if len({row["alias_file_hash"] for row in results}) != 1:
        raise ValueError("Alias configuration changed between modes; discard run and retry")
    if query_file_hash != digest(queries.read_bytes()):
        raise ValueError("Query file changed during evaluation; discard run and retry")
    versions = {}
    for package in ("lexmoryn", "numpy", "onnxruntime", "tokenizers", "pathspec"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    artifact = {
        "evaluation_version": 1,
        "dataset": payload.get("dataset"),
        "judgment_provenance": payload["judgment_provenance"],
        "query_file_sha256": query_file_hash,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "threads": threads,
            "versions": versions,
        },
        "protocol": {
            "modes": modes,
            "repeats": repeats,
            "top_k": 10,
            "strict_ids": True,
            "rrf_k": 60,
            "warmup_per_query": 1,
            "index_time_excludes_model_load": True,
            "peak_rss_scope": "fresh worker: model load, indexing and search",
        },
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    return {
        "output": str(output),
        "modes": [
            {
                k: row[k]
                for k in (
                    "mode",
                    "recall_at_5",
                    "recall_at_10",
                    "mrr_at_10",
                    "p50_latency_ms",
                    "p95_latency_ms",
                    "index_seconds",
                    "peak_rss_mib",
                )
            }
            for row in results
        ],
    }


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Use lexmoryn evaluate; this entry point is an isolated worker")
    print(json.dumps(_worker(json.load(sys.stdin))))
