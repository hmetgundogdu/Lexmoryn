# Research & Evaluation Plan

**Version:** 0.1 — proposed experiments; no results reported.  
**Related:** [White paper](WHITEPAPER.md) · [Architecture](ARCHITECTURE.md) · [Semantic schema](SEMANTIC_SCHEMA.md)

## Objective

Determine whether Lexmoryn needs a *new trained model*, or whether a well-engineered combination of existing lexical/embedding retrieval, extraction and evidence-grounded local memory already solves the problem adequately.

The initial task is **workspace-aware semantic understanding and retrieval**, not automatic file renaming. Naming is one possible downstream application.

## Research questions

| ID | Question | Evidence required |
| --- | --- | --- |
| RQ1 | Can a small parser extract useful concepts from arbitrary noisy filenames and content fragments? | Held-out span F1, normalization accuracy, failure taxonomy |
| RQ2 | Does locally learned alias/relation memory improve retrieval for project-specific terms? | Retrieval ablations with/without verified memory |
| RQ3 | Are filename/path signals additive to content signals? | Name-only vs. content-only vs. combined |
| RQ4 | Does exact identifier handling prevent false matches? | Near-identical version/ID challenge tests |
| RQ5 | Is a new model better enough than strong baselines to publish? | Reproducible accuracy/latency/cost comparison |
| RQ6 | Can the workspace context be updated and deleted correctly? | Change/retraction, leakage and ACL tests |

## 1. Dataset plan

### Source diversity

Target examples from multiple independent workspaces:
- Repositories with source code, manifests, configuration and documentation.
- Administrative documents, spreadsheets, exports and logs with permission-safe names.
- Model checkpoints, scientific datasets, CAD/media files, and other asset types represented by names and metadata.
- Multilingual names (including mixed-script and non-Latin paths), punctuation-heavy and abbreviation-rich cases.

Start with a **small human-annotated seed set**, then expand only after reviewing error categories. Synthetic examples may increase coverage but should never dominate the reported real-world test set.

### Licensing and privacy

Use openly licensed, public, clearly sourced content or data with explicit publication rights. Do not publish proprietary workplace filenames, paths, source code, user identifiers or document text. Retain per-example source attribution and license metadata where applicable. Keep private evaluation sets private when public distribution is not authorized.

### Split policy

- Split by **workspace/repository**, not random filename.
- Deduplicate and remove near-duplicate templates across splits.
- Include separate stress-test partitions for unseen languages, sectors, identifiers and aliases.
- Reserve a final test set before model selection and do not tune on it.
- Record dataset version, annotation guidelines, sampling methods and known biases.

### Annotation tasks

1. Meaningful source spans and segmentation boundaries.
2. Canonical concept, if supported; otherwise unknown.
3. Optional semantic role and typed attributes (date/version/identifier).
4. Local alias/relation claim with supporting and contradicting evidence.
5. Query relevance judgments for file and content-passage retrieval.
6. Explicit ambiguous, unanswerable and out-of-scope cases.

Use two annotators on a representative subset and adjudicate disagreements; report agreement and ambiguous labels rather than hiding them.

## 2. Benchmark tracks

### Track A — Semantic parsing

Input: basename/path and optionally short content.
Output: spans, normalized concepts, unresolved regions, proposed roles and evidence references.

Metrics:
- Span-level precision, recall and F1.
- Canonicalization accuracy on answerable items.
- Strict identifier preservation.
- Abstention accuracy and calibration (if confidence is modeled).
- Results by language, file type, domain and path morphology.

Baseline candidates:
- Deterministic rules/tokenizers/dictionaries.
- An off-the-shelf flexible NER extractor.
- A generic multilingual encoder with a task head.
- A general LLM as a *reference only*, evaluated for cost, speed and unsupported guesses.

### Track B — Local concept grounding

Input: source evidence and an ambiguous token such as 'Eagle'.
Output: alias proposals and workspace-specific relations.

Evaluate:
- Supported alias precision/recall and evidence correctness.
- Cross-workspace isolation (same token, different meanings).
- Contradiction handling, retraction and staleness after edits.
- False certainty rate on insufficient evidence.

Compare:
- No local memory.
- Manually curated alias dictionary.
- Automatic proposals without evidence gating.
- Evidence-grounded workspace memory with validation and retraction.

### Track C — Retrieval

Queries should mimic real navigation tasks:
- 'Find the service that persists leak test results.'
- 'Show the latest deployment configuration for arm64.'
- 'Locate the report tied to contract number 2026-009529.'
- 'Find the component locally called Eagle.'
- 'Locate the exact version v1.2.3, not v1.2.4.'

Each query requires judged relevant assets/passages. Avoid making one filename a near-literal copy of the query by default.

Baselines:
- Exact string, filename/path filters, grep/regex.
- BM25 on filename/path alone.
- BM25 on filename/path + extracted content.
- Dense retrieval on filenames and content (same corpus).
- Hybrid BM25 + dense, with published fusion parameters.
- Hybrid + contextual chunks.
- Hybrid + local alias/relation memory.
- Specialized parser and/or retriever, if trained.

Metrics:
- Recall@5/10/20, MRR@10, nDCG@10.
- False positives for strict identifiers.
- Answer evidence quality and source location correctness.
- p50/p95 query latency, indexing throughput, peak RAM/VRAM, storage.
- Incremental re-index time after modify/delete operations.

### Track D — Safety and lifecycle

Include:
- Unauthorized file access attempts and cross-tenant references.
- Prompt injection inside indexed content.
- Stale source, deleted file, renamed file and conflicting alias cases.
- Unsupported media, malformed input, symlink loops and malicious archive paths.
- Optional offline-only tests that verify no network requests.

Any unauthorized-content disclosure is a release blocker regardless of retrieval quality.

## 3. Controlled ablations

Run with the same corpus, same extractor versions and same query set.

| Ablation | Comparison |
| --- | --- |
| Name/path context | Names only vs. content only vs. combined |
| Workspace memory | Off vs. evidence-grounded memory |
| Graph expansion | Off vs. bounded graph expansion |
| Search mode | Exact/BM25 vs. dense vs. hybrid |
| Exact-ID filter | Off vs. on for numeric/version/hash queries |
| Context adaptation | Frozen global model vs. external workspace state |
| Model specialization | Generic extractor/encoder vs. fine-tuned candidate |

The system should identify which component yields a gain, rather than crediting all improvements to the model.

## 4. Reproducibility checklist

Publish, when legally possible:
- Frozen train/dev/test workspace lists and annotation protocol.
- Model name, checkpoint revision, license and configuration.
- Preprocessing, chunk size, embeddings, rank fusion and reranker settings.
- CPU/GPU hardware, operating system, library versions and batch sizes.
- End-to-end indexing/query runtime and peak memory.
- Statistical intervals across queries/workspaces and failure examples.
- Dataset cards, model cards, and explicit usage restrictions.

For Hugging Face, keep **model weights**, **dataset**, and **benchmark code** versioned independently.

## 5. Go / no-go criteria

Before training, choose baseline-dependent target improvements and an acceptable resource budget. Do **not** invent results or decide thresholds after viewing the held-out test set.

Proceed with specialized training only if:
1. Existing baselines show persistent and generalizable failures.
2. These failures can plausibly be addressed by supervised parsing, contrastive retrieval, or distillation.
3. Clean, legally usable labels are available.
4. The trained model has a defensible quality/latency/resource advantage, or offers a substantially better auditable semantic API.

Otherwise ship a benchmark, schema, extraction adapter, or context-memory library — not an unnecessary fine-tuned checkpoint.

## 6. Suggested sequence of work

**Milestone 0 — research assets:** finalize terminology, schema, license strategy, annotation format and evaluation harness.

**Milestone 1 — baseline:** deterministic parser; text/source extractor; filesystem discovery; BM25; off-the-shelf embedding baseline.

**Milestone 2 — evaluation dataset:** pilot workspaces, human judgments, held-out splits, multilingual and exactness challenges.

**Milestone 3 — grounded memory:** alias proposal, provenance, conflict management, incremental updates, authorization boundaries.

**Milestone 4 — comparative study:** ablations, efficiency/safety tests, error analysis and a transparent technical report.

**Milestone 5 — conditional model release:** model training/distillation if justified; publish Hugging Face artifacts with cards, reproducible scripts and known limitations.

## References for baselines and evaluation

- [BEIR benchmark](https://github.com/beir-cellar/beir)
- [Sentence Transformers semantic search](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)
- [Qdrant hybrid queries](https://qdrant.tech/documentation/hybrid-queries/)
- [Anthropic contextual retrieval](https://www.anthropic.com/research/contextual-retrieval)
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)
- [GLiNER](https://github.com/urchade/GLiNER)

*Nothing in this document constitutes a reported experimental result.*