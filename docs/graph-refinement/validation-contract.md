# Graph-refinement bundle validation contract

| | |
|---|---|
| **Status** | **Proposed.** The Platform Architect has not reviewed this schema. It is not wired into any workflow. |
| **Schema version** | `graph-refinement-bundle/0.1-proposed` |
| **Code** | `src/biosciences_temporal/graph_refinement/validation.py` |
| **Tests** | `tests/graph_refinement/` (offline, `-m unit`) |
| **Owner (proposed)** | Temporal Engineer, for the code. Platform Architect, for the claim/evidence/revision schema. Program Director, for the choice of host repo. |

## Purpose

This is the deterministic validation step for a bounded, evidence-first graph-refinement workflow.
A reasoning step proposes graph and claim changes. This validator checks the proposal's structure
and provenance, and a separate review follows. The validator is pure Python with Pydantic. It
makes no LLM, MCP, network, clock, or database calls, so it can run inside an activity or a test
without infrastructure.

**What a pass means:** the bundle is well-formed and every claim can be traced to identifiers,
evidence records and a revision.
**What a pass does not mean:** that any claim is scientifically true. The validator cannot say
that, and neither can a model review. The only way a claim becomes `accepted` is a named human
reviewer.

## Profiles

| Profile | Use for | Checks |
|---|---|---|
| `bundle` (default) | Output of a refinement pass | Everything below |
| `structural` | Existing KG JSON (for example the publication-pipeline `{slug}-knowledge-graph.json`) | Nodes, edges, identifiers, duplicates, closure, metadata counts |

```bash
uv run python -m biosciences_temporal.graph_refinement.validation bundle.json
uv run python -m biosciences_temporal.graph_refinement.validation kg.json --profile structural --format json
uv run python -m biosciences_temporal.graph_refinement.validation bundle.json --max-nodes 20 --max-claims 25
```

Exit codes: `0` valid (warnings allowed), `1` errors found, `2` the file is not readable as JSON.

## Bundle shape (proposed)

```json
{
  "schema_version": "graph-refinement-bundle/0.1-proposed",
  "revision": {"revision_id": "…", "parent_revision_id": null, "created_at": "2026-09-29T00:00:00Z",
               "producer": {"kind": "model|human|deterministic", "id": "…"},
               "content_digest": "sha256:… (optional; see below)"},
  "scope":    {"question": "…", "disease": "MONDO:…"},
  "nodes":    [{"id": "HGNC:…", "type": "Gene", "label": "…", "id_status": "resolved|unresolved|local_concept"}],
  "edges":    [{"source": "…", "target": "…", "type": "…"}],
  "evidence": [{"evidence_id": "…", "source": "<tool name>", "record_id": "<CURIE or URL>",
                "retrieved_at": "<ISO 8601 with timezone>", "content_digest": "sha256:<64 hex>"}],
  "claims":   [{"claim_id": "…", "subject": "…", "predicate": "…", "object": "…",
                "status": "supported|contradicted|hypothesis|inference|unresolved",
                "evidence_ids": ["…"], "derived_from": ["<claim_id>"], "genotype_dependent": false,
                "qualifiers": {"disease": "MONDO:…", "genotype": "…", "context_transfer": {"from": "…", "rationale": "…"}},
                "review": {"disposition": "pending|needs_review|accepted|rejected",
                           "reviewer_kind": "human|model|deterministic", "reviewer_id": "…"}}]
}
```

`content_digest` in `revision` is sha256 over canonical JSON (sorted keys, compact separators,
UTF-8) of the whole document except the `revision` block. Use it to detect content that changed
after the revision was recorded.

## Issue codes

Errors make `ok` false. Warnings do not. Codes are stable identifiers for automation.

| Code | Severity | Invariant |
|---|---|---|
| `NOT_AN_OBJECT`, `MISSING_SECTION` | error | Top level is an object. Required sections are present with the right type. |
| `UNSUPPORTED_SCHEMA_VERSION` | error | `bundle` profile only. |
| `MALFORMED_NODE`, `MALFORMED_EDGE`, `MALFORMED_CLAIM`, `MALFORMED_EVIDENCE` | error | Required fields are present. |
| `DUPLICATE_NODE_ID` | error | Node IDs are unique. |
| `DUPLICATE_NODE_ID_NORMALIZED` | error | No two IDs collide after case folding or colon repair (`NCT01294306` vs `NCT:01294306`). |
| `INVALID_CURIE` | error | IDs are `PREFIX:local`, except bare Ensembl `ENSG`/`ENST`. |
| `CURIE_PATTERN_MISMATCH` | error | The local part matches the registered pattern for its prefix. |
| `UNRESOLVED_IDENTIFIER` | error / warning | An unregistered prefix is an error unless the node declares `id_status: unresolved`, which makes it a warning. |
| `LOCAL_IDENTIFIER` | warning | The node declares `id_status: local_concept` (for example a framework). |
| `DANGLING_EDGE_ENDPOINT` | error | Both endpoints of every edge are nodes. |
| `DUPLICATE_EDGE` | warning | The same (source, type, target) appears more than once. |
| `COUNT_MISMATCH` | error | Any integer `metadata` count (`node_count`/`total_nodes`, `edge_count`/`total_edges`, `<type>_count`, `total_<type>_nodes`) equals the recomputed count. |
| `BUDGET_EXCEEDED` | error | Node and claim counts stay within the optional caps passed to the validator. |
| `DUPLICATE_CLAIM_ID`, `DUPLICATE_EVIDENCE_ID` | error | IDs are unique. |
| `INVALID_CLAIM_STATUS` | error | The status comes from the five-value vocabulary. Truth labels such as `validated` are rejected. |
| `CLAIM_ENDPOINT_NOT_IN_GRAPH` | error | A claim's subject and object are nodes. |
| `SUPPORTED_CLAIM_ON_UNRESOLVED_ENTITY` | error | A `supported` or `contradicted` claim touches only resolved identifiers. |
| `MISSING_EVIDENCE_REFERENCE` | error | A `supported` or `contradicted` claim cites at least one evidence record. |
| `UNKNOWN_EVIDENCE_REFERENCE` | error | Every cited evidence ID exists. |
| `INFERENCE_WITHOUT_BASIS`, `UNKNOWN_CLAIM_REFERENCE` | error | An `inference` lists existing claims in `derived_from`. |
| `MISSING_QUALIFIER` | error | `scope.disease` and every claim's `qualifiers.disease` are set. A genotype-dependent claim (by predicate or `genotype_dependent: true`) sets `qualifiers.genotype`. |
| `INVALID_QUALIFIER` | error | A disease qualifier is a resolved MONDO, EFO, DOID or ORPHA CURIE. |
| `CONTEXT_MISMATCH` | error | If a claim's disease differs from the scope disease, the claim declares `qualifiers.context_transfer`. |
| `INVALID_REVIEW` | error | Disposition and `reviewer_kind` come from their vocabularies. |
| `MODEL_ACCEPTANCE_NOT_ALLOWED` | error | Only `reviewer_kind: human` may set `accepted`. |
| `MISSING_REVIEWER` | error | Human acceptance names `reviewer_id`. |
| `MISSING_PROVENANCE_FIELD`, `INVALID_TIMESTAMP`, `INVALID_DIGEST` | error | Every evidence record has `source`, `record_id`, a timezone-aware `retrieved_at`, and a `sha256:` digest. |
| `UNUSED_EVIDENCE` | warning | Every evidence record is cited by some claim. |
| `EDGE_WITHOUT_CLAIM` | warning | Every edge is stated by some claim. |
| `MISSING_REVISION_FIELD`, `INVALID_REVISION`, `SELF_PARENT_REVISION`, `REVISION_DIGEST_MISMATCH` | error | Revision lineage and producer are explicit. `parent_revision_id` is always present and is `null` only for a root. A declared digest matches the content. |

## Identifier registry

`CURIE_REGISTRY` in the module comes from the connector `validate_id` regexes in `biosciences-mcp`
and ADR-001 Appendix A. It covers HGNC, UniProtKB, CHEMBL, NCT, WP, MONDO, EFO, DOID, ORPHA,
NCBIGene, PubChem, IUPHAR, STRING, DrugBank and PMID, plus bare `ENSG`/`ENST`. The validator
checks **syntax only**. It cannot tell whether an ID exists or maps to the intended entity. That
answer comes from the Fuzzy-to-Fact LOCATE → RETRIEVE evidence recorded in `evidence`.

## Decisions needed before this leaves "Proposed"

1. **Schema ownership and approval (Platform Architect).** The claim, evidence and revision
   fields, the claim-status and review-disposition vocabularies, and the digest rule are new. They
   do not redefine the ADR-001 §8 envelopes or Appendix A keys, but they need review before
   anything depends on them.
2. **Host repository (Program Director).** The planning draft recommends `biosciences-temporal`
   as host for a new refinement workflow type alongside CQ14. That is not yet approved. The module
   imports nothing Temporal-specific, so it can move if a different home is chosen.
3. **Edge predicate vocabulary.** ADR-001 §4 requires Biolink terms for entity responses. Existing
   KG JSON uses free-form, mixed-case edge types (`INHIBITS`, `inhibits`, `INHIBITOR`). The
   validator does not enforce Biolink predicates on graph edges until someone decides whether that
   rule applies to them.
4. **Genotype-dependent predicate list.** It is currently `synthetic_lethal_with`,
   `synthetic_lethal_context` and `genotype_selective_vulnerability`, plus a per-claim flag. A
   domain reviewer should confirm the list.
5. **Disease CURIE policy.** The bundle uses one scope disease. The artifacts disagree about which
   MONDO ID stands for NSCLC (`MONDO:0005233` in a v2 node property, `MONDO:0008903` in the
   systemic graph). The validator does not choose between them. A resolved lookup and a domain
   reviewer must.
6. **Budgets.** The draft's caps (20 nodes, 25 claims) are proposals. They are exposed as optional
   arguments with no defaults.

## Out of scope

Workflow wiring, activities, persistence and publication, live lookups, LLM review, and any
change to the CQ14 workflow or its provider path.
