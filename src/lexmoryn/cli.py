"""Local CLI. JSON responses are suitable for evaluation and evidence-linked navigation."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .embedding import DEFAULT_MODEL_DIR, Encoder, download_model
from .index import build_index
from .search import MODES, SearchEngine


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="lexmoryn")
    commands = cli.add_subparsers(dest="command", required=True)
    download = commands.add_parser(
        "download-model", help="Explicitly download pinned model weights"
    )
    download.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    for command in ("index", "search", "related", "memory", "evaluate"):
        sub = commands.add_parser(command)
        sub.add_argument("workspace", type=Path)
        sub.add_argument("--index", type=Path)
        if command in {"index", "search", "evaluate"}:
            sub.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
            sub.add_argument("--threads", type=int, default=2)
        if command == "index":
            sub.add_argument("--semantic", action="store_true", help="Embed with local weights")
        if command == "search":
            sub.add_argument("query")
            sub.add_argument("--mode", choices=MODES, default="lexical")
            sub.add_argument("--top-k", type=int, default=10)
            sub.add_argument("--no-strict-ids", action="store_true", help="Exact-ID ablation")
        if command == "related":
            sub.add_argument("path", help="Indexed workspace-relative file path")
        if command == "evaluate":
            sub.add_argument("queries", type=Path)
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--repeats", type=int, default=3)
            sub.add_argument("--lexical-only", action="store_true")
    return cli


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command == "download-model":
            result = download_model(args.model_dir)
        elif args.command == "index":
            if args.threads < 1:
                raise ValueError("threads must be positive")
            encoder = Encoder(args.model_dir, args.threads) if args.semantic else None
            result = build_index(args.workspace, args.index, encoder)
        elif args.command == "evaluate":
            from .evaluation import evaluate

            result = evaluate(
                args.workspace,
                args.queries,
                args.output,
                args.model_dir,
                args.repeats,
                args.threads,
                args.lexical_only,
                args.index,
            )
        else:
            if args.command == "search" and args.mode in {"dense", "hybrid", "memory"}:
                if args.threads < 1:
                    raise ValueError("threads must be positive")
                encoder = Encoder(args.model_dir, args.threads)
            else:
                encoder = None
            engine = SearchEngine(args.workspace, args.index, encoder)
            if args.command == "search":
                result = engine.search(args.query, args.mode, args.top_k, not args.no_strict_ids)
            elif args.command == "related":
                result = {"path": args.path, "relations": engine.related(args.path)}
            else:
                result = {"workspace_id": engine.meta["workspace_id"], "aliases": engine.memory()}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
        cli.exit(2, f"lexmoryn: {exc}\n")
    except KeyboardInterrupt:
        print("lexmoryn: interrupted", file=sys.stderr)
        return 130
