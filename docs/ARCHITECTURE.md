# Architecture — Lexmoryn (Draft v0.1)

> Design document, not an implementation report. Components, interfaces, and storage engines are proposals subject to benchmarking.

## 1. Scope and boundaries

Lexmoryn is a **semantic understanding and retrieval system for workspaces**, with a reusable model at its center. It is not restricted to filenames, one industry, or one language.

The project is intentionally divided into:

- **Core model:** transforms text/structured segments into semantic concepts, normalized representations, and optionally embeddings.
- **Extraction layer:** reads supported file formats and emits content/metadata in a common representation.
- **Workspace context engine:** maintains local evidence-backed aliases and relations separately from model weights.
- **Retrieval layer:** indexes and searches paths and content using exact, lexical, dense, and optional relation signals.
- **Application layer:** CLI, library, IDE or MCP integrations, and optional renaming policies.

The model never renames files or executes tools by itself. A caller owns all mutations.

## 2. Design principles

1. **Evidence-grounded:** every local inference points to specific source spans or explicit user confirmation.
2. **Workspace isolation:** identical strings may mean different things in different workspaces.
3. **Exactness:** versions, identifiers, paths, timestamps and hashes are preserved.
4. **Abstention:** an unknown meaning is preferable to an invented meaning.
5. **Rebuildability:** workspace memory and indexes can be reconstructed from retained source data and configuration.
6. **Incrementality:** changes must update only affected assets and dependent facts.
7. **Least privilege:** retrieved content cannot bypass caller-visible permissions.
8. **Extensibility:** extractor and storage backends are replaceable.

## 3. Logical data flow

```text
 [Discovery] --> [Extraction Adapters] --> [Normalized Segments]
                                             |
                                      [Semantic Parser]
                                             |
                          +------------------+-----------------+
                          |                                    |
                     [Concept Store]                      [Dense Encoder]
                          |                                    |
                  [Evidence Graph]                      [Vector Index]
                          |                                    |
                        [Lexical Index] <--- [Text + Names] --+
                          |                                    |
                          +--------------+---------------------+
                                         |
                                 [Hybrid Retriever]
                                         |
                             [Permissions + Rerank]
                                         |
                               [Grounded Search API]
```

## 4. Proposed modules

### 4.1 Workspace discovery

Input: one or more allowed directory roots or explicit asset lists.

Output: stable workspace-scoped asset identifiers, canonical relative paths, file metadata and hashes.

Requirements:
- Respect ignore rules and configurable size, depth, and extension limits.
- Handle symlinks and filesystem cycles safely; never escape authorized roots.
- Preserve the original Unicode path alongside any search-specific normalization.
- Watch changes where supported; otherwise use bounded rescan.
- Detect duplicate content independently of duplicate file names.

### 4.2 Extraction adapters

Suggested interface:

```text
extract(asset, options) -> segments[], structural_links[], diagnostics[]
```

Each segment should include a source locator: line range, JSON Pointer, page number, spreadsheet coordinate, time interval, or equivalent.

Candidate adapters:
- Plain text: UTF-8 and known text encodings with explicit error handling.
- Source code: Tree-sitter-compatible parsers for syntax-aware segmentation; language-specific symbol indexing is optional.
- JSON/YAML/XML/CSV: structured field extraction while preserving key paths.
- PDF/Office: text and table extractors with page/sheet provenance.
- Image/audio/video: metadata by default, optional OCR/transcription/captioning plugins with separate provenance and accuracy evaluation.
- Binary/unsupported: path and metadata only; surface an 'unsupported_content' diagnostic.

These adapters are **not** part of a purported single universal text model. Untrusted parsers must run with resource limits and hardened file handling.

### 4.3 Semantic model

Candidate input representation:
- Filename and path components as separate fields.
- Extracted content segments plus structural hints.
- Optional bounded workspace context retrieved from an evidence store.
- Language and modality indicators when known.

Candidate outputs:
- Open-vocabulary concepts and their source spans.
- Normalizations, roles, and unresolved strings.
- Supported or proposed relations.
- Optional dense representations for retrieval.

Model architecture is deliberately **undecided**. Investigate rule-based parsers, small encoders, flexible NER systems, and general embedding baselines before fine-tuning.

### 4.4 Workspace memory

The memory stores **hypotheses with provenance**, not unquestionable truths.

Proposed records:
- Concept node: canonical identifier, surface forms, scope.
- Alias claim: source phrase, target concept, supporting evidence, contradiction, state.
- Relation claim: source/target, relation type, evidence, state.
- Dependency: file revision and extractor/model version that produced the claim.

Statuses: `inferred`, `verified`, `conflicted`, `retracted`. Only explicit evidence or user confirmation may transition to `verified`. Repeated model generations alone are not independent evidence.

On file update/deletion:
1. Mark claims derived from invalidated versions as stale.
2. Re-extract/re-evaluate relevant sources.
3. Retract unsupported claims and invalidate dependent retrieval entries.
4. Keep an auditable change history as permitted by the retention policy.

Aliases should be scoped to a workspace or narrower namespace by default; an opt-in cross-workspace sharing mechanism would require explicit policy and evaluation.

### 4.5 Retrieval

Index four signal types:
- **Exact/lexical:** filenames, content terms, literal IDs, fuzzy tokens where safe.
- **Semantic:** embeddings of passages, paths, and structured representations.
- **Structural:** directory hierarchy, code symbols, references and file relationships.
- **Contextual:** grounded concept/alias graph.

Retrieval stages:
1. Enforce workspace and access scope.
2. Retrieve candidates from lexical and dense systems (plus optional exact-ID filters).
3. Expand a bounded number of grounded aliases/relations.
4. Fuse and/or rerank while retaining candidate provenance.
5. Recheck permissions and return cited passages or file paths.

Candidate approaches include Reciprocal Rank Fusion and learned reranking; choose based on measured quality/latency. An exact identifier filter must never be overridden by semantic proximity when the query expresses strict matching intent.

### 4.6 Storage

Storage implementation is intentionally open. A minimal local-first prototype could use:
- SQLite/FTS for asset metadata, inverted search and evidence tables.
- An in-process vector index or small local vector store.
- A relational edge table before introducing a full graph database.
- Content-addressed cache keys: (asset hash, extractor version, model version, options hash).

Benchmark the value of a dedicated graph/vector server before adding one. A database or infrastructure choice is not a research contribution by itself.

## 5. Proposed interface boundaries

All snippets are conceptual, not working SDK calls.

```text
parse(text, context=None) -> SemanticRepresentation
index(workspace_root, policy) -> IndexingReport
search(workspace_id, query, filters=None, top_k=10) -> SearchResult[]
explain(result_id) -> EvidenceTrace
forget(workspace_id, asset_ids) -> DeletionReport
```

**Example search result fields:** asset ID, relative path, matched segment locator, relevance components, evidence IDs, lexical exactness flags, index revision and data-access scope.

Search results must explain *what matched* without falsely claiming causal explanations for opaque model scores.

## 6. Operational and security requirements

### Privacy and authorization

- Default: process and index locally; disable network calls unless explicitly configured.
- Never store secrets or credentials in model prompts, benchmark samples, logs or telemetry.
- Apply per-workspace and per-file ACL filtering before candidates are exposed to any model or user.
- Treat vector embeddings and derived facts as potentially sensitive data.
- Provide deletion and retention semantics covering raw content, caches, embeddings and graph entries.

### Malicious content

Treat parsed documents and source comments as **untrusted input**. A sentence inside a repository is not an instruction to the system. Guard against prompt injection, command execution, decompression bombs, unsafe archive paths and filesystem traversal. Extraction must not require running arbitrary project code.

### Correctness

- Do not treat '.pdf' or '.jpg' as proof of actual format; detect type when possible.
- Preserve unrecognized terms, languages and identifiers.
- Never infer private relations across workspaces without authorization.
- Avoid making calibrated numeric confidence claims before calibration is measured.

## 7. Deployment profiles (proposed)

| Profile | Purpose | Expected dependencies |
| --- | --- | --- |
| Library | Parsing text and names | Minimal runtime |
| Local workspace | Offline indexing and search | Local extractors, stores |
| IDE/agent integration | Search tool for code agents | Local service/MCP adapter |
| Server (future) | Shared, ACL-aware workspaces | Auth, durable index services |

The local profile is the first research target; no throughput guarantee is implied.

## 8. Implementation sequence

1. Version the output contract and annotation format.
2. Implement discovery and text/source-code extractors.
3. Build an exact/BM25 baseline with source-linked results.
4. Add off-the-shelf embedding baseline and a hybrid comparison.
5. Implement evidence-scoped alias memory and incremental invalidation.
6. Evaluate on held-out workspaces with ablations.
7. Train or distill a custom model only if baselines expose repeatable gaps.

## 9. Open decisions

- Unified parser/retriever model vs. two smaller specialized encoders.
- Concept ontology depth and open-vocabulary relation encoding.
- Memory confidence estimation and human verification UX.
- Minimal supported languages and file types for the first benchmark.
- Vector index and graph storage based on workload rather than preference.
- Whether any cross-workspace knowledge transfer is permissible.

See [the white paper](WHITEPAPER.md), [the semantic schema](SEMANTIC_SCHEMA.md), and [the evaluation plan](RESEARCH_PLAN.md).