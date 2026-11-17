"""Lossless source locators and separate search normalization."""

from __future__ import annotations

import ast
import bisect
import hashlib
import re
from collections import Counter

ATOM = re.compile(r"[^\W_]+(?:[._:/-][^\W_]+)*", re.UNICODE)
WORD = re.compile(r"[^\W_]+", re.UNICODE)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tokens(text: str) -> list[str]:
    # Keep original compound identifiers as well as camelCase/path components.
    compounds = [match.group().casefold() for match in ATOM.finditer(text)]
    split = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", text)
    split = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", split)
    words = [match.group().casefold() for match in WORD.finditer(split)]
    return compounds + words


def strict_tokens(query: str) -> list[str]:
    """Digit-bearing atoms and long hex hashes are literal, case-sensitive constraints."""
    return list(
        dict.fromkeys(
            m.group()
            for m in ATOM.finditer(query)
            if any(c.isdigit() for c in m.group()) or re.fullmatch(r"[a-fA-F]{8,}", m.group())
        )
    )


def contains_literal(text: str, literal: str) -> bool:
    # A prefix of v1.2.30, INV-2049 or a longer hash is not an exact ID match.
    # Colons/slashes delimit labels and path segments; a terminal full stop is punctuation.
    boundary = r"(?<![\w.])" + re.escape(literal) + r"(?![\w-]|\.(?=\w))"
    return re.search(boundary, text) is not None


def symbols(text: str, suffix: str) -> list[tuple[str, int]]:
    if suffix == ".py":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            return []
        return sorted(
            (node.name, node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        )
    if suffix in {".cs", ".ts", ".tsx", ".js"}:
        pattern = r"\b(?:class|interface|enum|record|struct|function|type)\s+(\w+)"
        return [
            (m.group(1), text.count("\n", 0, m.start()) + 1) for m in re.finditer(pattern, text)
        ]
    return []


def chunks(path: str, text: str, suffix: str, max_chars: int = 1200) -> list[dict]:
    """Overlapping, bounded character windows; exact code-point columns and 1-based lines."""
    if not text:
        return []
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    names = symbols(text, suffix)
    result = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            newline = text.rfind("\n", start + max_chars // 2, end)
            if newline >= 0:
                end = newline + 1
        first = bisect.bisect_right(starts, start) - 1
        last = bisect.bisect_right(starts, end - 1) - 1
        result.append(
            {
                "id": digest(f"{path}:{start}:{end}".encode()),
                "path": path,
                "start_line": first + 1,
                "end_line": last + 1,
                "start_column": start - starts[first] + 1,
                "end_column": end - starts[last] + 1,
                "text": text[start:end],
                "symbols": [name for name, line in names if first + 1 <= line <= last + 1],
            }
        )
        if end == len(text):
            break
        # Prefer an overlap of whole lines, but also handle a single very long line.
        overlap = max(start + 1, end - 160)
        newline = text.find("\n", overlap, end - 1)
        start = newline + 1 if newline >= 0 else overlap
    return result


def term_counts(chunk: dict) -> Counter:
    return Counter(
        tokens(chunk["path"]) * 3 + tokens(" ".join(chunk["symbols"])) * 2 + tokens(chunk["text"])
    )
