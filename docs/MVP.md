# Experimental workspace retrieval MVP

Implements [issue #1](https://github.com/hmetgundogdu/Lexmoryn/issues/1) on `experiment/semantic-retrieval-mvp`. The original architecture and semantic schema describe the broader research target; the CLI's versioned snapshot/result format is a smaller implementation, not that full semantic contract.

## Setup and lexical search

Developed on macOS arm64 with Python 3.12; the evaluation harness also supports Linux. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from this repository:

```bash
uv sync --locked
uv run --offline lexmoryn index examples/workspace
uv run --offline lexmoryn search examples/workspace "persist leak test results"
uv run --offline lexmoryn search examples/workspace "v1.2.3" --mode exact
```

`index WORKSPACE` builds a full snapshot at `WORKSPACE/.lexmoryn/index.sqlite3`. Repeating it rescans additions, modifications, renames and deletions, then atomically replaces the old database. It does not edit source files. `--index /path/to/index.sqlite3` selects a different destination for `index`, `search`, `memory` and `related`.

Results are JSON: rank, path, snippet, inclusive 1-based start/end lines, 1-based code-point columns (end exclusive), source SHA-256, component scores/ranks, and related-file evidence. Text is preserved verbatim; line boundaries use LF. A metadata-only result has empty snippet and null locators. Scores are ranking signals, not calibrated confidence. Search returns at most one best passage per file.

## Local semantic and hybrid search

```bash
uv sync --locked --extra semantic
uv run lexmoryn download-model

# After installation/download, these operations require no network.
uv run --offline lexmoryn index examples/workspace --semantic
uv run --offline lexmoryn search examples/workspace "notify the customer after a refund" --mode dense
uv run --offline lexmoryn search examples/workspace "thermal pump inspection" --mode hybrid
uv run --offline lexmoryn search examples/workspace "payment processing service" --mode memory --top-k 2
```

The baseline is [multilingual E5 small](https://huggingface.co/intfloat/multilingual-e5-small), using [Xenova's ONNX conversion](https://huggingface.co/Xenova/multilingual-e5-small/tree/761b726dd34fb83930e26aab4e9ac3899aa1fa78). Revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78`, `onnx/model_quantized.onnx`, 384 dimensions, CPU ONNX Runtime, two threads, batch size eight. The base model's card declares MIT; the conversion card does not independently declare a license. Weights are downloaded separately and are not redistributed in this repository.

`download-model` is an explicit network operation restricted to the pinned model's five asset files. It writes checksums and identity to `lexmoryn-model.json`. The encoder reads only local files and verifies their checksums at load time; it does not import the model download client. No remote inference, custom Python model code, training, or workspace upload occurs. `--model-dir PATH` selects the cache for download/index/search/evaluate. Installations and model downloads need network; `uv run --offline` also prevents dependency resolution from using it.

Following the [E5 model's retrieval instructions](https://huggingface.co/intfloat/multilingual-e5-small), queries get `query: ` and chunks get `passage: `. Masked mean pooling and L2 normalization produce cosine vectors. Embedding input is original relative path, extracted symbols, then passage. The 512-token limit can truncate unusually long names or token-dense passages.

| Mode | Ranking |
| --- | --- |
| `exact` | Case-sensitive literal substring on path/content, with default ID constraints |
| `lexical` (default) | BM25, k1=1.2, b=0.75; path weight 3, symbol weight 2, content weight 1 |
| `dense` | Cosine similarity over the same paths/passages |
| `hybrid` | Equal-weight reciprocal rank fusion of BM25 and cosine, k=60 |
| `memory` | Hybrid with verified alias query expansion and a third ranking list of evidence-linked targets |

BM25 uses Unicode words, retained compound tokens, and camelCase components. There is no stop-word removal, stemming or synonym dictionary. Fusion ranks all eligible chunks before choosing the best chunk per file. Dense search is an in-process matrix scan. No vector service is required.

Digit-bearing tokens and long hexadecimal hashes in a query are case-sensitive literal constraints in **every** mode. A version such as `v1.2.3` excludes `v1.2.30` and `v1.2.3-rc1`. IDs remain in raw snippets and in lexical tokenization. This is a transparent heuristic: ordinary numbers and hardware names such as `arm64` also trigger it. `--no-strict-ids` disables constraints for ablations. The reported dense baseline includes the same exact-ID guard as the other modes; it is not unconstrained embedding-only search.

## Explicit relations and alias memory

```bash
uv run --offline lexmoryn related examples/workspace src/accounting/settlement.py
uv run --offline lexmoryn related examples/workspace web/checkout.ts
uv run --offline lexmoryn memory examples/workspace
```

`related` returns one-hop incoming/outgoing links with source path, line range, literal quote and source hash. Python AST imports, relative TypeScript/JavaScript import-shaped references, and local Markdown links resolve only to existing, unambiguous workspace paths. Python modules are parsed, never executed. This is static path resolution, not proof of runtime calls. TypeScript and Markdown use limited regular expressions; aliases, URL-encoded paths, package resolution, dynamic imports, and C# namespace resolution are outside v0.

To add a workspace alias, create `WORKSPACE/.lexmoryn-aliases.json` and re-index:

```json
{
  "version": 1,
  "aliases": [{
    "alias": "Eagle",
    "canonical": "payment processing service",
    "targets": ["src/EagleService.cs"],
    "status": "verified",
    "evidence": {
      "path": "docs/architecture.md",
      "start_line": 3,
      "end_line": 3,
      "quote": "Eagle is the payment processing service implemented in [src/EagleService.cs](../src/EagleService.cs)."
    }
  }]
}
```

The quote must occur within the specified source lines and explicitly contain the alias, canonical phrase and every target path. Targets must exist in the indexed workspace. `verified` means a curated assertion backed by that literal declaration; the software verifies provenance, not whether the source's assertion is true. There is no inferred numeric confidence. `inferred` claims remain visible but never expand retrieval. The fixture's Falcon claim demonstrates this separation.

Missing/changed evidence produces `retracted` claims. Incompatible verified meanings for the same alias produce `conflicted` claims; neither is used. Editing the alias file invalidates old memory until re-indexing. Changes/deletions to a source or target suppress memory and related results immediately through SHA-256 checks. `memory` reports current validity without rewriting the snapshot. Full rescans rebuild memory; there is no persistent claim history or automatic alias induction.

## Discovery, storage and update limits

- Extracts UTF-8 `.md`, `.txt`, `.cs`, `.py`, `.ts`, `.tsx`, `.js`, `.json`, `.yaml`, `.yml`. Source symbols use Python AST or small C#/TS/JS declaration patterns. JSON/YAML are plain text with line locations, not parsed field schemas.
- Chunks are at most 1,200 Unicode code points with up to 160 characters of overlap, preferring newline boundaries. Very long lines use precise columns. Unsupported formats, binary text candidates, invalid UTF-8, and files over 2 MiB retain only path/metadata and a diagnostic. All regular files are SHA-256 hashed using streaming reads.
- Skips symlinks, hidden paths, `node_modules`, `__pycache__`, `dist`, `build`, the output index, and nested `.gitignore`/`.lexmorynignore` rules. The hidden alias and ignore files are configuration, not searchable documents. `.github` is also hidden under this MVP policy. Changes to discovery/ignore rules take effect at the next rescan.
- Relative paths and chunk IDs are stable across identical rescans. Snapshot metadata binds the index to one canonical workspace root; moving a workspace requires re-indexing. Another workspace cannot reuse its index or memory.
- Search hashes eligible files again and excludes changed, deleted, unreadable or symlink-replaced sources. That cost is included in measured latency. It does not discover new files until re-indexing. Indexed raw snippets remain on disk until the next successful replacement or removal of the index.
- SQLite contains local raw snippets, metadata, aliases, relation evidence and optional vectors. Cache/download/index paths are gitignored. No real private workspace is used in the committed fixtures or report.
- This is a single-user local experiment. It has no multi-tenant authorization layer, hostile concurrent-writer isolation, OCR, PDF/Office extraction, ANN index, generative answers or autonomous file changes. Keep existing OS permissions on the workspace and index; this is not a shared search service.

## Reproduce measurements and tests

```bash
# 40 seed files plus 960 deterministic, repeated-template distractors.
# The generator requires a new destination and will not overwrite an existing workspace.
uv run --offline python examples/make_workspace.py .lexmoryn/benchmark-workspace --files 1000
uv run --offline lexmoryn evaluate .lexmoryn/benchmark-workspace examples/evaluation/queries.json \
  --output docs/experiments/issue-1-results.json

# Small seed-only comparison, or lexical-only without downloading a model.
uv run --offline lexmoryn evaluate examples/workspace examples/evaluation/queries.json \
  --lexical-only --output .lexmoryn/lexical-results.json

uv run --offline ruff check src tests examples/make_workspace.py
uv run --offline ruff format --check src tests examples/make_workspace.py
uv run --offline pytest -q
LEXMORYN_TEST_MODEL=.lexmoryn/models/multilingual-e5-small uv run --offline pytest -q
```

The harness builds a fresh index and runs queries in an isolated process **for each mode**, checks identical corpus hashes, and records Recall@5/@10, MRR@10, p50/p95 warm search latency, index time, peak process RSS, exact-ID false positives, source locator fidelity and judged passage overlap. Each query has one untimed warm-up and three timed repetitions. Model/engine loading times are recorded separately from indexing/search. It uses disposable indexes, so `evaluate` does not alter the workspace index.

The 28 relevance judgments include synonyms, filename-only and content-only clues, abbreviations, aliases, multilingual queries, versions, IDs and hashes. They are agent-authored synthetic fixtures, not independent human labels, and there is no held-out real workspace. Template distractors test scale and ambiguity, not realistic corpus diversity. The [report](experiments/ISSUE_1_REPORT.md) explains measured failures. The next research step is independent human review and evaluation on permission-safe real workspaces before tuning ranking or considering model training.
