# Lexmoryn: Evidence-Grounded Semantic Understanding and Retrieval in Heterogeneous Workspaces

**Research white paper — Version 0.1 (proposal)**  
**Date:** 18 November 2026  
**Project:** [Lexmoryn](https://github.com/hmetgundogdu/Lexmoryn)  
**Status:** Conceptual design; no trained model, implemented system, or experimental results are claimed.

## Abstract

Real-world workspaces consist of filenames, nested paths, source code, documents, structured files, logs, and media-derived metadata. Their meaning is often encoded in short, noisy strings, local abbreviations, implicit naming conventions, and relationships that are meaningful only within one workspace. Traditional lexical search preserves exact terms but misses many conceptual associations; general-purpose dense retrieval can discover semantic similarity but may blur strict identifiers and fail to recognize local project vocabulary. Contextual retrieval and knowledge graph systems address parts of this problem, but they do not by themselves establish whether a small, specialized semantic parsing model can economically improve retrieval across heterogeneous workspace files.

Lexmoryn proposes **an evidence-grounded workspace semantic layer**: format-aware extraction, semantic parsing of both names and content, provenance-aware local concept memory, and hybrid retrieval with exact-identifier safeguards. Its primary research hypothesis is that adding a compact, structured representation of local concepts and relationships to strong lexical and embedding baselines can improve retrieval quality and/or efficiency under realistic multilingual and cross-workspace conditions. This document defines the problem, a proposed architecture, falsifiable experiments, limitations, and reproducibility requirements. No superiority or novelty claim is asserted without evidence.

## 1. Motivation

A workspace is not necessarily a collection of conventional documents. Examples include:

- Source code, package manifests, configuration, commit-linked paths, and symbol references.
- Business files, contracts, spreadsheets, reports, and scanned or generated documents.
- Images, video, audio, CAD files, model checkpoints, and application artifacts.
- Dataset exports, scientific measurements, machine logs, and proprietary file formats.

Consider the string 'yolov11n_best_epoch100.pt'. A generic retriever can embed the string but may not distinguish a model identifier from checkpoint selection or training epoch. Conversely, 'EagleService.cs' might name a payment-processing service in one repository and a bird-classification component in another. The same surface token therefore has **workspace-dependent meaning**.

Lexmoryn's goal is not to infer information that cannot be established from available evidence. File extensions are useful signals, not proof of underlying content; names may be misleading; content can be stale; and a model must be able to abstain.

## 2. Research problem

Let a workspace W contain assets A = {a_1, ..., a_n}. For an asset a, the observable signals are:

- p(a): relative path, basename, extension and hierarchy;
- c(a): extractable content segments and structural features;
- m(a): optional file/system metadata;
- r(a): observed references and relationships to other assets.

Let K_W be a versioned, workspace-scoped knowledge state derived from these observations, not a globally shared truth database.

We propose three tasks:

1. **Semantic parsing:** produce concepts, spans, roles, normalized forms, unresolved spans and evidence references from p(a) and c(a).
2. **Context adaptation:** propose, validate, update and retract workspace-specific aliases and relations in K_W.
3. **Retrieval:** given query q, rank assets or content passages using lexical, dense, structural and optional K_W signals.

The parser is not responsible for constructing a final filename. Naming policy belongs to downstream clients. Model output is structured and auditable.

### 2.1 Hypotheses

**H1 — parsing:** Specialized handling of filename/path morphology, abbreviated identifiers and structured content can improve concept-span F1 and canonicalization accuracy relative to generic information-extraction baselines on held-out workspaces.

**H2 — grounding:** Evidence-backed local aliases and relationships can improve Recall@k and MRR/nDCG on queries containing workspace-specific terminology compared with the same retrieval stack without local memory.

**H3 — efficiency:** A small parser plus sparse retrieval can produce a competitive accuracy/latency/cost tradeoff compared with direct full-workspace LLM analysis. Efficiency is measured, not presumed.

**H4 — robustness:** Exact-match safeguards reduce harmful conflation of versions, IDs, numbers and hashes relative to unconstrained semantic-only ranking.

Each hypothesis can be rejected. If existing retrieval stacks meet the same quality and latency targets without a new model, the outcome should be a benchmark or library rather than unnecessary model weights.

## 3. Proposed system

```text
                      WORKSPACE
      paths | content | metadata | relationships
                         |
        secure discovery + format-specific extractors
                         |
             segments / symbols / spans
                         |
          semantic parser / optional encoder
                         |
           concepts + evidence references
                         |
              WORKSPACE MEMORY (K_W)
      aliases | typed relations | confidence | expiry
                         |
    +--------------------+--------------------+
    |                    |                    |
 lexical/exact     dense retrieval     structure/graph
    |                    |                    |
    +--------------------+--------------------+
                         |
                 fusion + reranking
                         |
       cited file/passage results and structured API
```

### 3.1 Ingestion and extractors

The system separates file-format extraction from semantic understanding. A core parser should be able to accept plain UTF-8 text or structured, provenance-carrying segments. Adapters may use source parsers (e.g., Tree-sitter), PDF/text extractors, spreadsheet and JSON/XML readers, OCR, speech transcription, or visual models where justified. Binary input without a suitable extractor must not be treated as text.

Each segment retains an asset identifier, relative path, content hash, extractor/version, location coordinates (line range, field path, page, or time interval), and access-control scope. Large assets are chunked using format-aware boundaries where possible.

### 3.2 Semantic representation

Each concept retains **surface form**, **canonical form (when supported)**, **role (when supported)**, **source span**, **status**, and **evidence**. The schema must not require a fixed catalogue of industries. Unknown labels may remain unresolved or be expressed as open-vocabulary terms. If a canonical meaning cannot be grounded, preserve the literal surface token.

For example, a filename token 'prod' may map to 'production' in a deployment workspace. The same token may mean something else elsewhere. Scope and evidence are mandatory for such interpretations.

### 3.3 Context and local learning

The base model provides broad linguistic/structural priors. The workspace memory K_W stores local knowledge **without modifying the base weights**:

- Proposed entity or concept aliases and their source spans.
- Typed links such as 'calls', 'configured_by', 'mentioned_in', or a workspace-specific relation.
- Supporting and contradicting evidence, revision metadata, and validity state.
- Explicit confidence/calibration metadata, including an option to abstain.

An alias such as 'Eagle' -> 'payment_processing_service' must be supported by observed code references, documentation, or explicit confirmation. The system should distinguish **inferred**, **verified**, **conflicted**, and **retracted** states. New evidence can revise or remove old relations. Edges should not become permanent facts just because they were retrieved repeatedly.

Workspace memory must be partitioned by tenant and access control; the same alias can mean different things in different projects. Deletion and source changes propagate to derived entries.

### 3.4 Retrieval and ranking

Lexmoryn proposes hybrid retrieval, not embedding-only search. Candidates may be produced by:

- Filename/path prefix, exact, regex and lexical/BM25 matching.
- Dense vector retrieval over names, structured descriptions and content chunks.
- Symbol/path/hierarchy indexes and relation traversal.
- Optional cross-encoder or lightweight reranking.

Use rank fusion (e.g., Reciprocal Rank Fusion) as a transparent baseline. Identifier constraints should be represented explicitly: 'v1.2.3' and 'v1.2.4' are related but **not equivalent**; exact IDs, hashes and timestamps should never be silently normalized into a different value. Search responses include source locations and relevant evidence so users or agents can verify the result.

### 3.5 Incremental maintenance

Track content hashes and extractor/model versions. When an asset changes, re-extract affected segments, invalidate dependent relations and vectors, and update indices. A deleted file must not remain accessible through a stale derived memory edge. Maintain deterministic, inspectable indexing logs.

## 4. Model development strategy

The intended deliverable is not necessarily a single end-to-end generative LLM. The study will compare:

- Deterministic parsing (tokenization, rules, dictionaries, format parsers).
- General-purpose multilingual embedding encoders.
- Open/zero-shot entity extraction approaches.
- Small encoder models trained for span tagging, canonicalization and/or retrieval.
- A larger model as an optional teacher or evaluation reference, with privacy constraints.

Possible training objectives include span boundary prediction, pairwise alias resolution, contrastive query-to-evidence alignment, and relation classification. Multi-task learning is a *candidate*, not a commitment. Separate parser and retriever checkpoints may outperform a unified model.

A staged approach is preferred: benchmark existing components first, identify failures, and fine-tune or distill only when a defensible improvement is demonstrated.

## 5. Data and evaluation

### 5.1 Dataset design

Build a multilingual, multi-domain corpus covering filenames, path components, short fragments, long text and extracted structured segments. Include mixed scripts, abbreviations, camelCase, snake_case, punctuation, version strings, aliases, near-duplicate identifiers and ambiguous terms. Use synthetic examples to supplement, not replace, independently annotated realistic cases.

**Critical split:** train/validation/test must be separated by workspace (and where possible organization and template), not by randomly splitting almost-identical filenames. Report language- and domain-specific performance, especially on unseen concepts.

Gold labels should include concept spans, acceptable canonicalizations, roles, evidence sources, unknown/abstain decisions, local alias support, and query-to-file or query-to-passage relevance judgments. Store annotation guidelines and inter-annotator agreement where available.

### 5.2 Baselines and ablations

At minimum compare:
1. Exact/regex/path heuristics.
2. BM25 over names and extracted content.
3. General-purpose dense retrieval over the same inputs.
4. Dense + BM25 hybrid retrieval.
5. Hybrid + contextual chunks.
6. Hybrid + workspace memory, with and without semantic parsing.
7. Proposed trained parser/retriever, if training is justified.

Ablate name-only versus content-only versus combined inputs; memory on/off; relation-expansion on/off; and strict identifier handling on/off. Holding the underlying extraction and corpus constant is necessary for fair comparisons.

### 5.3 Metrics

- **Parsing:** span precision/recall/F1, concept normalization accuracy, exact identifier retention, abstention calibration, unresolved-token coverage.
- **Local knowledge:** supported alias precision, evidence correctness, stale relation rate, cross-workspace leakage rate.
- **Retrieval:** Recall@5/10/20, MRR@10, nDCG@10, lexical-versus-semantic error breakdown.
- **Systems:** p50/p95 query latency, CPU throughput, indexed bytes, RAM/VRAM peak, incremental update cost, energy and per-file indexing cost where measurable.
- **Security:** unauthorized result rate and deletion/ACL propagation correctness.

Report uncertainty intervals over held-out queries and workspaces, not single cherry-picked examples. No benchmark numbers are asserted in this proposal.

## 6. Threat model, ethics, and limitations

Workspace data may contain secrets, personal information, proprietary code, contracts or regulated records. A local-first default is therefore required: no automatic external API calls, uploads or telemetry. Connectors and third-party extractors need explicit permissions. Respect file ACLs **before retrieval**, and at every expansion or reranking stage. Derived embeddings and knowledge entries can leak information and must be protected and removable.

Treat file contents as **untrusted data**, not executable instructions to an agent. Enforce sandboxing/limits on parsers, archive extraction and document rendering. Never execute a file merely to understand it. Guard against malicious paths, symlinks, oversized archives, resource exhaustion and prompt injection in documents.

There are unavoidable epistemic limits: a filename does not prove a file's type, a reference does not prove an alias, and a similarity score is not a causal explanation. The system should expose ambiguity and contradictory sources. Non-text media understanding requires optional modality-specific components and separate evaluations.

Dataset releases require documented provenance, licenses, consent or lawful basis where appropriate, and de-identification; synthetic datasets must be clearly labeled. Do not publish private filenames or content from real workplaces.

## 7. Prior work and positioning

Lexmoryn builds upon existing concepts rather than asserting they are novel:

- **GraphRAG** uses extracted graph structures to augment retrieval and question answering [1].
- **Contextual Retrieval** enriches chunks with local document context prior to indexing [2].
- **Hybrid retrieval** combines exact/sparse and semantic/dense signals [3].
- **Sentence Transformers** provides dense and reranking components suitable for baselines [4].
- **GLiNER** explores flexible entity recognition without a conventional fixed NER label set [5].
- **Tree-sitter** supports incremental structural parsing of source code [6].
- **BEIR** motivates evaluating retrieval across diverse tasks instead of one narrow benchmark [7].

The proposed contribution — **if substantiated** — is the measured interaction between heterogeneous file/name parsing, locally grounded concept adaptation, and secure low-cost retrieval. A negative result is still useful if supported by reproducible experiments.

## 8. Milestones and publication criteria

**Phase A — definition:** schema, annotator protocol, privacy policy, test taxonomy and reproducible evaluation harness.

**Phase B — baselines:** lexical, hybrid and embedding comparisons on representative data; error analysis with held-out workspaces.

**Phase C — contextual memory:** evidence-backed alias graph, update/retraction semantics, multi-tenant isolation, memory ablations.

**Phase D — specialized model (conditional):** small model training/distillation based on measured baseline failure modes.

**Phase E — release (conditional):** Hugging Face model cards and dataset cards, scripts, fixed splits, licenses, limitations, metrics, sample notebooks and a versioned API.

Before publication of a model, require reproducible quality gain on at least one well-defined task, no unacceptable regression on exact identifiers or access control, and an explicit efficiency budget. Thresholds should be registered before final evaluation.

## 9. Conclusion

Lexmoryn studies whether a workspace can be interpreted as a **living, evidence-linked semantic environment** rather than a flat bag of files or embeddings. The key proposal is to keep general model knowledge separate from scoped local memory, preserve source evidence and uncertainty, and combine that context with reliable lexical retrieval. Whether a new trained model is warranted is an empirical question. The immediate output of this project is a falsifiable specification and benchmark plan.

## References

1. Microsoft Research, **GraphRAG** (project and methodology): https://github.com/microsoft/graphrag
2. Anthropic, **Introducing Contextual Retrieval**, 2024: https://www.anthropic.com/research/contextual-retrieval
3. Qdrant documentation, **Hybrid Queries**: https://qdrant.tech/documentation/hybrid-queries/
4. Sentence Transformers documentation, **Semantic Search**: https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html
5. GLiNER project and documentation: https://github.com/urchade/GLiNER
6. Tree-sitter, **Incremental Parsing**: https://github.com/tree-sitter/tree-sitter
7. Thakur et al., **BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval** (2021): https://arxiv.org/abs/2104.08663

---

**Note:** This white paper is a design and research proposal, not a peer-reviewed paper or a performance report.