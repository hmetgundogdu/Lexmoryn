# Issue #1: local workspace retrieval experiment

Date: 2026-11-18. Branch: `experiment/semantic-retrieval-mvp`. [Implementation/setup](../MVP.md), [raw measurements](issue-1-results.json), [query judgments](../../examples/evaluation/queries.json).

## Protocol and provenance

The corpus contains **1,000 synthetic files**: 40 authored seed files and 960 deterministic distractors made from eight repeated topic templates. There are 1,000 chunks and six explicit relations. The 28 queries cover synonyms, abbreviations, filenames, content, local aliases, Turkish/Spanish/Chinese, and near-identical versions/IDs/hashes. Three unsupported-format placeholders contribute path/metadata only.

**Judgments are agent-authored and curated against the synthetic source spans, not independently human-annotated.** No real private workspace was indexed for these results. This is a development experiment, not a held-out or generalizable quality benchmark. Repeated distractors create an artificial ambiguity challenge and do not represent 1,000 independent realistic documents.

Hardware: Apple M4, 10 logical CPUs, 16 GiB RAM; macOS 26.6.2 arm64; Python 3.12.13; two ONNX CPU threads. `uv.lock` and the JSON artifact record dependency versions. Encoder: quantized multilingual E5 small, pinned ONNX revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78`, mean pooling, 384 dimensions, batch eight, 512-token limit. BM25 uses k1=1.2/b=0.75 and path/symbol/content weights 3/2/1; RRF uses k=60 with equal component weights. Ranking parameters were fixed before the comparison.

Every mode builds a fresh index and searches the **same corpus and queries in a separate process**. Corpus SHA-256: `5c48ba3caf0f70162a9471457790b1ec1dec526d1a3409eb62c05ef0a6161796`. The harness also checks alias-file identity. Recall is macro-averaged over judged files; MRR uses the first relevant file. Search returns one best passage per file, at most ten results.

Each query has one untimed warm-up and three timed repetitions (84 timed searches per mode). Latency includes query encoding, current-source hashing, ranking, and evidence checks. Index time excludes dependency/model download and model loading; model loading took about 0.32–0.33 s, engine loading about 0.014–0.019 s. Peak RSS covers model loading, indexing and searching in that mode's fresh process. These are warm filesystem-cache timings from one machine, without statistical intervals.

## Measured results

| Mode | Recall@5 | Recall@10 | MRR@10 | p50 / p95 (ms) | Index time (s) | Peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 + exact-ID guard | 0.893 | 0.893 | 0.929 | 68.11 / 75.89 | 0.229 | 32.9 |
| Dense + exact-ID guard | 0.929 | 0.964 | 0.941 | 72.47 / 75.47 | 3.329 | 748.9 |
| Hybrid | 0.893 | 0.893 | 0.893 | 73.80 / 79.11 | 3.397 | 749.4 |
| Hybrid + local memory | 0.929 | 0.929 | 0.929 | 73.20 / 76.97 | 3.476 | 749.0 |

The lexical SQLite snapshot is 786,432 bytes; semantic snapshots are 2,428,928 bytes, excluding the separately downloaded model. All four modes enforce the same strict-ID filter. The standalone `exact` substring CLI is available; the lexical table row measures BM25 with ID constraints rather than literal matching of full natural-language queries.

Each mode returned **0 identifier-presence false positives among 8 results** from six identifier-bearing queries. This counts whether the requested literal occurs in the file/path, not whether every result is topically relevant. It demonstrates the guard on these cases, not unguarded dense exactness or universal identifier correctness.

Returned text/line/column fidelity was **114/114, 213/213, 215/215 and 215/215** respectively. Retrieved judged passages overlapped their annotated lines **24/24, 26/26, 24/24 and 26/26**. Metadata-only results are excluded from locator denominators. Most fixtures fit in one chunk, so these figures are primarily source-fidelity checks; long-line/overlap behavior is separately tested and needs richer passage-level evaluation.

## Examples, failures and trade-offs

- **Local ambiguity, q04 `Eagle`:** ordinary hybrid returns bird documents and neither judged project file in its top ten. Verified memory returns `src/EagleService.cs` first and `docs/architecture.md` second. For q03 `payment processing service`, memory moves the source implementation from hybrid rank four to rank one. Evidence is the literal declaration at `docs/architecture.md:3`; inferred Falcon claims never expand search.
- **Cross-language retrieval, q23:** dense ranks `文档/温度.md` first for “stop the cooling pump when its temperature is too high”. Lexical, hybrid and memory miss it at ten. Equal-weight RRF favors documents present in both lists, even when their English words are less relevant. This is a baseline failure, not evidence that hybrid always helps.
- **Difficult paraphrase, q21:** the Turkish refund notification is dense rank nine and absent from other modes' top ten. Memory only addresses documented project vocabulary; it does not solve unrelated paraphrase failures.
- **Filename-only navigation, q10:** the unsupported pump-image placeholder is found through its path, with null passage location. Its bytes are never treated as an extracted description. Exact-version queries exclude `v1.2.30` and `v1.2.3-rc1` when searching `v1.2.3`.
- **Evidence navigation:** `related ... src/accounting/settlement.py` resolves `from .ledger import Ledger` on line one to `src/accounting/ledger.py`. Markdown and TypeScript provide additional explicit examples. These are static references, not runtime behavior claims.

Dense achieves the best Recall@10 here but uses about 23 times the lexical peak RAM. Memory helps the constructed alias case and improves ordinary hybrid, while remaining below dense's overall Recall@10. Full rescans and per-query source hashes keep lifecycle behavior inspectable at a measurable cost. The experiment gives no reason to train a new model yet.

## Reproduction and remaining work

From the repository root after `uv sync --locked --extra semantic` and the explicit `lexmoryn download-model` step:

```bash
uv run --offline python examples/make_workspace.py .lexmoryn/benchmark-workspace --files 1000
uv run --offline lexmoryn evaluate .lexmoryn/benchmark-workspace examples/evaluation/queries.json \
  --output .lexmoryn/reproduced-results.json
```

Generation requires a new destination; reuse an already generated corpus for another evaluation. The implementation is isolated on the experiment branch, with original research documents retained. No source renaming, model training, private data publication or implicit content upload was added.

Validation: 31 tests pass with real local weights, including network-denied semantic search, exact-ID boundaries, source locators, full rescan changes/deletions, stale evidence, conflicting/inferred claims, workspace isolation and atomic index replacement; Ruff lint/format checks pass. Next steps are independent human relevance review, permission-safe real workspaces and longer documents, then held-out ablations of path weighting, strict-ID handling and fusion. The prototype has no OCR/Office extraction, incremental vector reuse, approximate vector index, general alias induction, or multi-user authorization layer.
