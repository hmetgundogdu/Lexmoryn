# Semantic Output Contract (Draft)

**Contract version:** `0.1-draft`  
**Status:** Design proposal only. No running implementation or stable SDK exists.

## Why a contract?

Lexmoryn is intended to emit **semantic information**, not a hardcoded filename. Applications may use that information for organization, agent retrieval, filtering, classification, or user-defined naming rules.

This schema is intentionally broad enough to represent filenames, code, ordinary text, configuration and content extracted from heterogeneous files.

## Design rules

- Preserve the **original source text** and any identifiers exactly.
- Keep source spans and **evidence** available for auditing.
- Treat roles and relation types as open vocabulary, not as a universal mandatory ontology.
- Support unknown and ambiguous interpretations without inventing canonical forms.
- A confidence value is optional and must not imply calibration until validated.
- Do not include private file content in a public benchmark or log without authorization.
- Schema versioning is mandatory; extensions must not silently change the semantics of existing fields.

## Example A — filename-only input

Input: `backup_prod_db_2026_11_18.sql`

The following is an **illustrative expected output**, not an actual prediction.

```json
{
  "schema_version": "0.1-draft",
  "workspace_id": "example-1",
  "source": {
    "asset_id": "asset-001",
    "path": "backup_prod_db_2026_11_18.sql",
    "kind": "filename",
    "text": "backup_prod_db_2026_11_18.sql",
    "revision": "example-hash"
  },
  "concepts": [
    {
      "id": "c1",
      "surface": "backup",
      "canonical": "backup",
      "role": "operation",
      "span": {"start": 0, "end": 6},
      "status": "observed",
      "confidence": null,
      "evidence_ids": ["e1"]
    },
    {
      "id": "c2",
      "surface": "prod",
      "canonical": "production",
      "role": "environment",
      "span": {"start": 7, "end": 11},
      "status": "inferred",
      "confidence": null,
      "evidence_ids": ["e2"]
    },
    {
      "id": "c3",
      "surface": "db",
      "canonical": "database",
      "role": "asset_kind",
      "span": {"start": 12, "end": 14},
      "status": "inferred",
      "confidence": null,
      "evidence_ids": ["e3"]
    }
  ],
  "attributes": [
    {
      "key": "date",
      "value": "2026-11-18",
      "raw_parts": ["2026", "11", "18"],
      "evidence_ids": ["e1"]
    },
    {
      "key": "file_extension",
      "value": "sql",
      "evidence_ids": ["e1"]
    }
  ],
  "relations": [],
  "evidence": [
    {
      "id": "e1",
      "kind": "source_span",
      "asset_id": "asset-001",
      "locator": {"type": "filename"}
    },
    {
      "id": "e2",
      "kind": "workspace_rule",
      "reference": "environment-aliases:prod"
    },
    {
      "id": "e3",
      "kind": "workspace_rule",
      "reference": "technical-abbreviations:db"
    }
  ],
  "unresolved": []
}
```

Note: this example assumes the specified workspace rules exist; it does not claim that `prod` must universally mean production or `db` must universally mean database. The date is derived from contiguous filename components, but the semantic date *role* (created, exported, backup time) remains unspecified.

## Example B — workspace-dependent alias

Imagine the following *hypothetical* evidence:
- `src/EagleService.cs`: a class named `EagleService`;
- `docs/architecture.md`: states that Eagle handles payment processing.

The system could propose the following concept claim:

```json
{
  "workspace_id": "payments-workspace",
  "concept": {
    "surface": "Eagle",
    "canonical": "payment_processing_service",
    "role": "workspace_alias",
    "status": "inferred",
    "confidence": null,
    "evidence_ids": ["eagle-docs-1", "eagle-source-1"]
  },
  "alternatives": [],
  "unresolved": []
}
```

A different workspace can have a different meaning for `Eagle`. Even in this workspace, contradictory evidence may downgrade the claim to `conflicted` or `retracted`.

## Suggested fields

### Source

| Field | Meaning |
| --- | --- |
| `asset_id` | Stable workspace-scoped asset key |
| `path` | Original relative path, unmodified |
| `kind` | Filename, content chunk, code symbol, metadata, etc. |
| `text` | Raw segment where applicable |
| `revision` | Content/version identifier used for invalidation |
| `locator` | Source position: line/column, JSON Pointer, page, sheet/cell, time, etc. |

### Concept

| Field | Meaning |
| --- | --- |
| `id` | Stable within one representation |
| `surface` | Original observed substring/token |
| `canonical` | Proposed normalized form or `null` |
| `role` | Optional open-vocabulary semantic label |
| `span` | Start-inclusive, end-exclusive offsets within the source text |
| `status` | `observed`, `inferred`, `verified`, `conflicted`, or `retracted` |
| `confidence` | Optional calibrated estimate, otherwise `null` |
| `evidence_ids` | Links to evidence records supporting the interpretation |

### Relation

A relation record should contain `subject_id`, `predicate`, `object_id`, `status`, `evidence_ids`, and optionally validity metadata. A relation is a *claim*, not proof.

### Evidence

Evidence records must indicate how the claim arose: literal source span, another file's span, static analysis, human confirmation or a declared workspace rule. An inference should never masquerade as a literal observation.

## Span convention

For v0.1, offsets are proposed as **Unicode code-point indexes** within the exact `source.text` (start-inclusive, end-exclusive). Implementations using UTF-8 bytes or UTF-16 code units must explicitly convert and test multilingual/emoji cases. File/line/page locations are separate from character span coordinates. This convention is provisional until validated against target language runtimes.

## Normalization policy

The model may suggest:
- `camelCase` / `snake_case` word segmentation;
- abbreviation expansion supported by context;
- Unicode-aware canonical forms for search;
- recognized dates, versions and other typed values.

But it **must not**:
- silently discard unmatched source spans;
- rewrite hashes, version numbers, IDs or timestamps;
- pretend a guessed meaning is verified;
- force every file into 'document type' categories;
- construct or apply a final filename without an explicit downstream naming policy.

## Compatibility and errors

Return diagnostics for unsupported binary types, truncated content, extraction errors and missing permissions. Use explicit `null`/unknown values rather than fabricating content. The representation should be serializable, stable across re-indexing given identical inputs/configuration, and adaptable to JSONL datasets.

See [architecture](ARCHITECTURE.md) and [research plan](RESEARCH_PLAN.md) for intended producers and evaluations.