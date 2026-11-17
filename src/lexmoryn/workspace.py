"""Bounded discovery, literal relations, and evidence-gated local alias claims."""

from __future__ import annotations

import ast
import json
import posixpath
import re
from pathlib import Path, PurePosixPath

from pathspec import GitIgnoreSpec

from .text import chunks, digest

TEXT_SUFFIXES = {".md", ".txt", ".cs", ".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml"}
SKIP_DIRS = {"node_modules", "__pycache__", "dist", "build"}
MEMORY_FILE = ".lexmoryn-aliases.json"
MAX_BYTES = 2 * 1024 * 1024


def local_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts or "\\" in relative:
        raise ValueError(f"Expected a workspace-relative path: {relative}")
    path = root.joinpath(*rel.parts)
    if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
        raise ValueError(f"Symlink skipped: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {relative}")
    return path


def read_local(root: Path, relative: str) -> bytes:
    path = local_path(root, relative)
    with path.open("rb") as stream:
        return stream.read(MAX_BYTES + 1)


def file_hash(root: Path, relative: str) -> str:
    import hashlib

    path = local_path(root, relative)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _rules(root: Path, directory: Path, inherited: list) -> list:
    rules = list(inherited)
    for name in (".gitignore", ".lexmorynignore"):
        relative = (directory / name).relative_to(root).as_posix()
        try:
            data = read_local(root, relative)
        except (OSError, ValueError):
            continue
        if len(data) <= MAX_BYTES:
            spec = GitIgnoreSpec.from_lines(data.decode("utf-8", errors="replace").splitlines())
            rules.append((directory, spec))
    return rules


def discover(root: Path, excluded: set[Path]) -> tuple[list[dict], list[dict], dict, list[dict]]:
    assets, segments, texts, diagnostics = [], [], {}, []
    stack = [(root, [])]
    while stack:
        directory, inherited = stack.pop()
        rules = _rules(root, directory, inherited)
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            diagnostics.append(
                {"path": directory.relative_to(root).as_posix(), "reason": type(exc).__name__}
            )
            continue
        for path in entries:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                diagnostics.append({"path": relative, "reason": "symlink_skipped"})
                continue
            if path in excluded or path.name.startswith(".") or path.name in SKIP_DIRS:
                continue
            ignored = False
            for base, spec in rules:
                scoped = path.relative_to(base).as_posix() + ("/" if path.is_dir() else "")
                decision = spec.check_file(scoped).include
                if decision is not None:
                    ignored = decision
            if ignored:
                continue
            if path.is_dir():
                stack.append((path, rules))
                continue
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                sha = file_hash(root, relative)
                content = read_local(root, relative) if stat.st_size <= MAX_BYTES else None
                # Detect concurrent edits during the scan rather than storing inconsistent evidence.
                if content is not None and digest(content) != sha:
                    raise ValueError("file_changed_during_scan")
                status = "unsupported_content"
                text = None
                if content is None:
                    status = "size_limit"
                elif path.suffix.lower() in TEXT_SUFFIXES:
                    try:
                        text = content.decode("utf-8")
                        if "\x00" in text or any(ord(c) < 9 for c in text):
                            text, status = None, "binary_content"
                        else:
                            status = "text"
                    except UnicodeDecodeError:
                        status = "invalid_utf8"
                assets.append(
                    {
                        "path": relative,
                        "sha256": sha,
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "status": status,
                    }
                )
                extracted = chunks(relative, text, path.suffix.lower()) if text else []
                if text is not None:
                    texts[relative] = text
                if not extracted:
                    extracted = [
                        {
                            "id": digest(f"{relative}:path".encode()),
                            "path": relative,
                            "start_line": None,
                            "end_line": None,
                            "start_column": None,
                            "end_column": None,
                            "text": "",
                            "symbols": [],
                        }
                    ]
                segments.extend(extracted)
                if status != "text":
                    diagnostics.append({"path": relative, "reason": status})
            except (OSError, ValueError) as exc:
                diagnostics.append(
                    {
                        "path": relative,
                        "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    }
                )
    return sorted(assets, key=lambda a: a["path"]), segments, texts, diagnostics


def relations(texts: dict[str, str], assets: list[dict]) -> list[dict]:
    known = {asset["path"]: asset for asset in assets}
    result = []

    def add(source: str, target: str, kind: str, start: int, end: int, quote: str):
        if target in known and target != source:
            edge = {
                "source": source,
                "target": target,
                "kind": kind,
                "status": "observed",
                "evidence": {
                    "path": source,
                    "start_line": start,
                    "end_line": end,
                    "quote": quote,
                    "sha256": known[source]["sha256"],
                },
            }
            if edge not in result:
                result.append(edge)

    for source, text in sorted(texts.items()):
        suffix = PurePosixPath(source).suffix.lower()
        parent = posixpath.dirname(source)
        if suffix in {".md", ".txt"}:
            # Only literal workspace paths, never remote URLs or basename guesses.
            for match in re.finditer(r"\[[^\]\n]*\]\(([^\s)]+)\)", text):
                raw = match.group(1).split("#", 1)[0]
                if not raw or ":" in raw or raw.startswith("/"):
                    continue
                target = posixpath.normpath(posixpath.join(parent, raw))
                line = text.count("\n", 0, match.start()) + 1
                add(source, target, "markdown_link", line, line, match.group())
        if suffix in {".ts", ".tsx", ".js"}:
            pattern = r"""(?:\bfrom\s*|\bimport\s*|\brequire\s*\()(["'])(\.[^"']+)\1"""
            for match in re.finditer(pattern, text):
                base = posixpath.normpath(posixpath.join(parent, match.group(2)))
                candidates = [
                    base,
                    *(base + ext for ext in (".ts", ".tsx", ".js")),
                    base + "/index.ts",
                    base + "/index.js",
                ]
                hits = [p for p in candidates if p in known]
                if len(hits) == 1:
                    line = text.count("\n", 0, match.start()) + 1
                    add(source, hits[0], "import", line, line, match.group())
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError, RecursionError):
                continue
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [(alias.name, "") for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = parent if node.level else ""
                    for _ in range(max(0, node.level - 1)):
                        base = posixpath.dirname(base)
                    module = (node.module or "").replace(".", "/")
                    modules = [(module, base)]
                    modules += [(posixpath.join(module, alias.name), base) for alias in node.names]
                for module, base in modules:
                    module = module.replace(".", "/")
                    stem = posixpath.normpath(posixpath.join(base, module))
                    hits = [p for p in (stem + ".py", stem + "/__init__.py") if p in known]
                    if len(hits) == 1:
                        quote = ast.get_source_segment(text, node) or ""
                        add(source, hits[0], "import", node.lineno, node.end_lineno, quote)
    return result


def aliases(root: Path, texts: dict, assets: list[dict]) -> tuple[list[dict], str | None]:
    try:
        raw = read_local(root, MEMORY_FILE)
    except FileNotFoundError:
        return [], None
    if len(raw) > MAX_BYTES:
        raise ValueError("Alias file exceeds size limit")
    memory = json.loads(raw)
    if not isinstance(memory, dict) or memory.get("version") != 1:
        raise ValueError("Alias file must contain version: 1 and an aliases list")
    claims = memory.get("aliases")
    if not isinstance(claims, list):
        raise ValueError("aliases must be a list")
    known = {a["path"]: a for a in assets}
    output = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Alias claims must be objects")
        alias, canonical, targets = (claim.get(k) for k in ("alias", "canonical", "targets"))
        if (
            not isinstance(alias, str)
            or not alias.strip()
            or not isinstance(canonical, str)
            or not canonical.strip()
            or not isinstance(targets, list)
            or not targets
            or not all(isinstance(p, str) for p in targets)
        ):
            raise ValueError("Alias requires nonempty alias, canonical and targets")
        evidence = claim.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("Alias evidence must be an object")
        status = claim.get("status", "inferred")
        if status not in {"inferred", "verified"}:
            raise ValueError("Input alias status must be inferred or verified")
        row = {
            "alias": alias,
            "canonical": canonical,
            "targets": targets,
            "status": status,
            "evidence": dict(evidence),
        }
        path = evidence.get("path")
        if path is not None and not isinstance(path, str):
            raise ValueError("Alias evidence path must be a string")
        first, last, quote = (evidence.get(k) for k in ("start_line", "end_line", "quote"))
        lines = texts.get(path, "").splitlines(keepends=True)
        valid = (
            type(first) is int
            and type(last) is int
            and 1 <= first <= last <= len(lines)
            and isinstance(quote, str)
            and bool(quote.strip())
        )
        if valid:
            span = "".join(lines[first - 1 : last])
            valid = (
                quote in span
                and alias.casefold() in quote.casefold()
                and canonical.casefold() in quote.casefold()
                and all(p in known and p in quote for p in targets)
            )
        if valid:
            row["evidence"]["sha256"] = known[path]["sha256"]
        else:
            row.update(status="retracted", reason="missing_or_changed_literal_evidence")
        output.append(row)
    for alias in {row["alias"].casefold() for row in output}:
        rows = [r for r in output if r["alias"].casefold() == alias and r["status"] == "verified"]
        meanings = {(r["canonical"].casefold(), tuple(sorted(r["targets"]))) for r in rows}
        if len(meanings) > 1:
            for row in rows:
                row.update(status="conflicted", reason="incompatible_verified_claims")
    return output, digest(raw)
