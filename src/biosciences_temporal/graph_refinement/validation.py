"""Deterministic validator for graph-refinement bundles (proposed contract v0.1).

Checks structural and provenance invariants only: identifier syntax, duplicates,
edge closure, metadata counts, claim-to-evidence references, required
disease/genotype/context qualifiers, review dispositions, and revision metadata.

A passing report means the bundle is well-formed and traceable. It does NOT mean
any claim is scientifically true; only a named human reviewer can accept a claim.

The claim/evidence/revision contract is a proposal pending Platform Architect
review (docs/graph-refinement/validation-contract.md). Pure stdlib + Pydantic:
no LLM, MCP, network, clock, or filesystem access outside the CLI.

    uv run python -m biosciences_temporal.graph_refinement.validation bundle.json
    uv run python -m biosciences_temporal.graph_refinement.validation kg.json --profile structural
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeGuard

from pydantic import BaseModel, ConfigDict, computed_field

SCHEMA_VERSION = "graph-refinement-bundle/0.1-proposed"

# Local-ID patterns for resolved CURIEs, keyed by prefix. Sourced from the
# connector validate_id regexes in biosciences-mcp and ADR-001 Appendix A.
# Changing this registry is a platform decision (Platform Architect review).
CURIE_REGISTRY: dict[str, re.Pattern[str]] = {
    "HGNC": re.compile(r"^\d+$"),
    "UniProtKB": re.compile(r"^[A-Z][A-Z0-9]{5,9}$"),
    "CHEMBL": re.compile(r"^\d+$"),
    "NCT": re.compile(r"^\d{8}$"),
    "WP": re.compile(r"^WP\d+$"),
    "MONDO": re.compile(r"^\d{7}$"),
    "EFO": re.compile(r"^\d{7}$"),
    "DOID": re.compile(r"^\d+$"),
    "ORPHA": re.compile(r"^\d+$"),
    "NCBIGene": re.compile(r"^\d+$"),
    "PubChem": re.compile(r"^CID\d+$"),
    "IUPHAR": re.compile(r"^\d+$"),
    "STRING": re.compile(r"^\d+\.ENSP\d+$"),
    "DrugBank": re.compile(r"^DB\d{5}$"),
    "PMID": re.compile(r"^\d+$"),
}

# Ensembl identifiers are used unprefixed by the connectors (ADR-001 Appendix A).
BARE_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^ENSG\d{11}$"),
    re.compile(r"^ENST\d{11}$"),
)

DISEASE_PREFIXES = frozenset({"MONDO", "EFO", "DOID", "ORPHA"})

# Bare forms that are really a prefixed ID with the colon missing, e.g. NCT01294306.
_BARE_PREFIXED = re.compile(r"^(NCT|CHEMBL|HGNC|WP)[:_]?(\d+)$", re.IGNORECASE)

CLAIM_STATUSES = frozenset(
    {"supported", "contradicted", "hypothesis", "inference", "unresolved"}
)
EVIDENCE_REQUIRED_STATUSES = frozenset({"supported", "contradicted"})
REVIEW_DISPOSITIONS = frozenset({"pending", "needs_review", "accepted", "rejected"})
ACTOR_KINDS = frozenset({"human", "model", "deterministic"})
ID_STATUSES = frozenset({"resolved", "unresolved", "local_concept"})
GENOTYPE_DEPENDENT_PREDICATES = frozenset(
    {
        "synthetic_lethal_with",
        "synthetic_lethal_context",
        "genotype_selective_vulnerability",
    }
)
EVIDENCE_FIELDS = (
    "evidence_id",
    "source",
    "record_id",
    "retrieved_at",
    "content_digest",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TYPE_COUNT_KEY = re.compile(r"^(?:total_([a-z]+)_nodes|([a-z]+)_count)$")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Profile(StrEnum):
    BUNDLE = "bundle"
    """Full proposed contract: graph + claims + evidence + scope + revision."""
    STRUCTURAL = "structural"
    """Graph only: identifiers, duplicates, edge closure, metadata counts."""


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    path: str
    message: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile
    schema_version: str
    issues: tuple[Issue, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]


def compute_content_digest(doc: Mapping[str, Any]) -> str:
    """sha256 over canonical JSON of everything except the ``revision`` block."""
    body = {k: v for k, v in doc.items() if k != "revision"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_graph(
    doc: Any,
    *,
    profile: Profile = Profile.BUNDLE,
    max_nodes: int | None = None,
    max_claims: int | None = None,
) -> ValidationReport:
    """Validate a parsed JSON document. Never raises on malformed input."""
    v = _Validator(profile)
    v.run(doc, max_nodes=max_nodes, max_claims=max_claims)
    return ValidationReport(
        profile=profile, schema_version=SCHEMA_VERSION, issues=tuple(v.issues)
    )


def normalize_identifier(identifier: str) -> str:
    """Key for near-duplicate detection: case-folded, missing colon restored."""
    text = identifier.strip()
    bare = _BARE_PREFIXED.match(text)
    if bare:
        return f"{bare.group(1).upper()}:{bare.group(2)}"
    return text.upper()


def _nonempty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _is_tz_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _normalize_predicate(predicate: str) -> str:
    text = predicate.strip().lower()
    text = text.removeprefix("biolink:")
    return re.sub(r"[\s\-]+", "_", text)


class _Validator:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.issues: list[Issue] = []
        self.node_ids: set[str] = set()
        self.resolved_ids: set[str] = set()
        self.evidence_ids: set[str] = set()
        self.cited_evidence: set[str] = set()
        self.claim_ids: set[str] = set()
        self.claim_triples: set[tuple[str, str, str]] = set()

    def add(
        self, code: str, path: str, message: str, severity: Severity = Severity.ERROR
    ) -> None:
        self.issues.append(
            Issue(code=code, severity=severity, path=path, message=message)
        )

    def run(self, doc: Any, *, max_nodes: int | None, max_claims: int | None) -> None:
        if not isinstance(doc, Mapping):
            self.add("NOT_AN_OBJECT", "$", "Document must be a JSON object.")
            return
        bundle = self.profile is Profile.BUNDLE

        if bundle:
            version = doc.get("schema_version")
            if version != SCHEMA_VERSION:
                self.add(
                    "UNSUPPORTED_SCHEMA_VERSION",
                    "schema_version",
                    f"Expected {SCHEMA_VERSION!r}, found {version!r}.",
                )

        required = ["nodes", "edges"] + (["claims", "evidence"] if bundle else [])
        sections: dict[str, list[Any]] = {}
        for name in required:
            value = doc.get(name)
            if isinstance(value, list):
                sections[name] = value
            else:
                self.add("MISSING_SECTION", name, f"'{name}' must be a list.")
                sections[name] = []

        self.check_nodes(sections["nodes"])
        self.check_edges(sections["edges"])
        self.check_counts(doc.get("metadata"), sections["nodes"], sections["edges"])
        self.check_budget("nodes", len(sections["nodes"]), max_nodes)

        if not bundle:
            return

        scope_disease = self.check_scope(doc.get("scope"))
        self.check_evidence(sections["evidence"])
        self.check_claims(sections["claims"], scope_disease)
        self.check_budget("claims", len(sections["claims"]), max_claims)
        self.check_revision(doc)

        for index, record in enumerate(sections["evidence"]):
            if isinstance(record, Mapping):
                eid = record.get("evidence_id")
                if _nonempty_str(eid) and eid not in self.cited_evidence:
                    self.add(
                        "UNUSED_EVIDENCE",
                        f"evidence[{index}]",
                        f"Evidence {eid!r} is not cited by any claim.",
                        Severity.WARNING,
                    )
        for index, edge in enumerate(sections["edges"]):
            if isinstance(edge, Mapping):
                triple = (edge.get("source"), edge.get("type"), edge.get("target"))
                if (
                    all(isinstance(t, str) for t in triple)
                    and triple not in self.claim_triples
                ):
                    self.add(
                        "EDGE_WITHOUT_CLAIM",
                        f"edges[{index}]",
                        f"Edge {triple} is not stated by any claim.",
                        Severity.WARNING,
                    )

    # --- graph ------------------------------------------------------------

    def check_nodes(self, nodes: Sequence[Any]) -> None:
        seen: dict[str, int] = {}
        seen_normalized: dict[str, str] = {}
        for index, node in enumerate(nodes):
            path = f"nodes[{index}]"
            if not isinstance(node, Mapping):
                self.add("MALFORMED_NODE", path, "Node must be an object.")
                continue
            node_id = node.get("id")
            if not _nonempty_str(node_id):
                self.add(
                    "MALFORMED_NODE",
                    f"{path}.id",
                    "Node id must be a non-empty string.",
                )
                continue
            if not _nonempty_str(node.get("type")):
                self.add(
                    "MALFORMED_NODE", f"{path}.type", f"Node {node_id!r} has no type."
                )
            id_status = node.get("id_status", "resolved")
            if id_status not in ID_STATUSES:
                self.add(
                    "MALFORMED_NODE",
                    f"{path}.id_status",
                    f"id_status must be one of {sorted(ID_STATUSES)}, found {id_status!r}.",
                )

            if node_id in seen:
                self.add(
                    "DUPLICATE_NODE_ID",
                    f"{path}.id",
                    f"Node id {node_id!r} already used at nodes[{seen[node_id]}].",
                )
            else:
                seen[node_id] = index
                key = normalize_identifier(node_id)
                if key in seen_normalized:
                    self.add(
                        "DUPLICATE_NODE_ID_NORMALIZED",
                        f"{path}.id",
                        f"Node id {node_id!r} duplicates {seen_normalized[key]!r} after normalization.",
                    )
                else:
                    seen_normalized[key] = node_id
            self.node_ids.add(node_id)

            if (
                self.check_identifier(node_id, id_status, f"{path}.id")
                and id_status == "resolved"
            ):
                self.resolved_ids.add(node_id)

    def check_identifier(self, node_id: str, id_status: Any, path: str) -> bool:
        """Return True when node_id is a well-formed resolved identifier."""
        if any(p.match(node_id) for p in BARE_ID_PATTERNS):
            return True
        prefix, sep, local = node_id.partition(":")
        if not sep:
            self.add(
                "INVALID_CURIE",
                path,
                f"{node_id!r} is not a PREFIX:local CURIE"
                + (
                    f" (did you mean {normalize_identifier(node_id)!r}?)"
                    if _BARE_PREFIXED.match(node_id)
                    else ""
                ),
            )
            return False
        pattern = CURIE_REGISTRY.get(prefix)
        if pattern is not None:
            if pattern.match(local):
                return True
            self.add(
                "CURIE_PATTERN_MISMATCH",
                path,
                f"{node_id!r}: local id does not match the {prefix} pattern {pattern.pattern}.",
            )
            return False
        if id_status == "local_concept":
            self.add(
                "LOCAL_IDENTIFIER",
                path,
                f"{node_id!r} is a declared local concept, not a database entity.",
                Severity.WARNING,
            )
        elif id_status == "unresolved":
            self.add(
                "UNRESOLVED_IDENTIFIER",
                path,
                f"{node_id!r} is declared unresolved; resolve it with LOCATE -> RETRIEVE before supporting claims.",
                Severity.WARNING,
            )
        else:
            self.add(
                "UNRESOLVED_IDENTIFIER",
                path,
                f"Prefix {prefix!r} is not a registered source; resolve {node_id!r} or declare "
                "id_status 'unresolved' / 'local_concept'.",
            )
        return False

    def check_edges(self, edges: Sequence[Any]) -> None:
        seen: dict[tuple[str, str, str], int] = {}
        for index, edge in enumerate(edges):
            path = f"edges[{index}]"
            if not isinstance(edge, Mapping):
                self.add("MALFORMED_EDGE", path, "Edge must be an object.")
                continue
            source, target, etype = (
                edge.get("source"),
                edge.get("target"),
                edge.get("type"),
            )
            missing = [
                k
                for k, val in (("source", source), ("target", target), ("type", etype))
                if not _nonempty_str(val)
            ]
            if missing:
                self.add(
                    "MALFORMED_EDGE", path, f"Edge is missing {', '.join(missing)}."
                )
                continue
            assert (
                isinstance(source, str)
                and isinstance(target, str)
                and isinstance(etype, str)
            )
            for role, endpoint in (("source", source), ("target", target)):
                if endpoint not in self.node_ids:
                    self.add(
                        "DANGLING_EDGE_ENDPOINT",
                        f"{path}.{role}",
                        f"Edge {source} -[{etype}]-> {target}: {role} {endpoint!r} is not a node.",
                    )
            triple = (source, etype, target)
            if triple in seen:
                self.add(
                    "DUPLICATE_EDGE",
                    path,
                    f"Edge {triple} repeats edges[{seen[triple]}].",
                    Severity.WARNING,
                )
            else:
                seen[triple] = index

    def check_counts(
        self, metadata: Any, nodes: Sequence[Any], edges: Sequence[Any]
    ) -> None:
        if not isinstance(metadata, Mapping):
            return
        by_type = Counter(
            n["type"].lower()
            for n in nodes
            if isinstance(n, Mapping) and isinstance(n.get("type"), str)
        )
        for key, declared in metadata.items():
            if not isinstance(declared, int) or isinstance(declared, bool):
                continue
            if key in ("node_count", "total_nodes"):
                actual = len(nodes)
            elif key in ("edge_count", "total_edges"):
                actual = len(edges)
            else:
                match = _TYPE_COUNT_KEY.match(key)
                if not match:
                    continue
                node_type = match.group(1) or match.group(2)
                if node_type in ("node", "edge"):
                    continue
                actual = by_type.get(node_type, 0)
            if actual != declared:
                self.add(
                    "COUNT_MISMATCH",
                    f"metadata.{key}",
                    f"Metadata declares {declared}, graph contains {actual}.",
                )

    def check_budget(self, what: str, count: int, limit: int | None) -> None:
        if limit is not None and count > limit:
            self.add(
                "BUDGET_EXCEEDED",
                what,
                f"{count} {what} exceeds the budget of {limit}.",
            )

    # --- scope, evidence, claims ------------------------------------------

    def check_disease_curie(self, value: Any, path: str) -> bool:
        if not _nonempty_str(value):
            self.add(
                "MISSING_QUALIFIER",
                path,
                "A disease qualifier (resolved disease CURIE) is required.",
            )
            return False
        prefix, sep, local = value.partition(":")
        pattern = CURIE_REGISTRY.get(prefix)
        if (
            not sep
            or prefix not in DISEASE_PREFIXES
            or pattern is None
            or not pattern.match(local)
        ):
            self.add(
                "INVALID_QUALIFIER",
                path,
                f"{value!r} is not a resolved disease CURIE ({', '.join(sorted(DISEASE_PREFIXES))}).",
            )
            return False
        return True

    def check_scope(self, scope: Any) -> str | None:
        if not isinstance(scope, Mapping):
            self.add(
                "MISSING_SECTION",
                "scope",
                "'scope' must be an object with a disease qualifier.",
            )
            return None
        disease = scope.get("disease")
        return disease if self.check_disease_curie(disease, "scope.disease") else None

    def check_evidence(self, evidence: Sequence[Any]) -> None:
        for index, record in enumerate(evidence):
            path = f"evidence[{index}]"
            if not isinstance(record, Mapping):
                self.add(
                    "MALFORMED_EVIDENCE", path, "Evidence record must be an object."
                )
                continue
            for field in EVIDENCE_FIELDS:
                if not _nonempty_str(record.get(field)):
                    self.add(
                        "MISSING_PROVENANCE_FIELD",
                        f"{path}.{field}",
                        f"Evidence requires '{field}'.",
                    )
            eid = record.get("evidence_id")
            if _nonempty_str(eid):
                if eid in self.evidence_ids:
                    self.add(
                        "DUPLICATE_EVIDENCE_ID",
                        f"{path}.evidence_id",
                        f"Evidence id {eid!r} is repeated.",
                    )
                self.evidence_ids.add(eid)
            retrieved = record.get("retrieved_at")
            if _nonempty_str(retrieved) and not _is_tz_timestamp(retrieved):
                self.add(
                    "INVALID_TIMESTAMP",
                    f"{path}.retrieved_at",
                    f"{retrieved!r} is not an ISO 8601 timestamp with a timezone.",
                )
            digest = record.get("content_digest")
            if _nonempty_str(digest) and not _DIGEST.match(digest):
                self.add(
                    "INVALID_DIGEST",
                    f"{path}.content_digest",
                    f"{digest!r} is not 'sha256:<64 lowercase hex>'.",
                )

    def check_claims(self, claims: Sequence[Any], scope_disease: str | None) -> None:
        # First pass collects ids so derived_from may reference later claims.
        for claim in claims:
            if isinstance(claim, Mapping) and _nonempty_str(claim.get("claim_id")):
                self.claim_ids.add(claim["claim_id"])

        seen: set[str] = set()
        for index, claim in enumerate(claims):
            path = f"claims[{index}]"
            if not isinstance(claim, Mapping):
                self.add("MALFORMED_CLAIM", path, "Claim must be an object.")
                continue
            missing = [
                k
                for k in ("claim_id", "subject", "predicate", "object", "status")
                if not _nonempty_str(claim.get(k))
            ]
            if missing:
                self.add(
                    "MALFORMED_CLAIM", path, f"Claim is missing {', '.join(missing)}."
                )
                continue
            cid, status = claim["claim_id"], claim["status"]
            subject, predicate, obj = (
                claim["subject"],
                claim["predicate"],
                claim["object"],
            )
            if cid in seen:
                self.add(
                    "DUPLICATE_CLAIM_ID",
                    f"{path}.claim_id",
                    f"Claim id {cid!r} is repeated.",
                )
            seen.add(cid)
            self.claim_triples.add((subject, predicate, obj))

            if status not in CLAIM_STATUSES:
                self.add(
                    "INVALID_CLAIM_STATUS",
                    f"{path}.status",
                    f"{status!r} is not one of {sorted(CLAIM_STATUSES)}. Truth labels such as "
                    "'validated' are not claim statuses; acceptance is a human review disposition.",
                )

            for role, endpoint in (("subject", subject), ("object", obj)):
                if endpoint not in self.node_ids:
                    self.add(
                        "CLAIM_ENDPOINT_NOT_IN_GRAPH",
                        f"{path}.{role}",
                        f"Claim {cid!r}: {role} {endpoint!r} is not a node.",
                    )
                elif (
                    status in EVIDENCE_REQUIRED_STATUSES
                    and endpoint not in self.resolved_ids
                ):
                    self.add(
                        "SUPPORTED_CLAIM_ON_UNRESOLVED_ENTITY",
                        f"{path}.{role}",
                        f"Claim {cid!r} is {status!r} but {endpoint!r} is not a resolved identifier.",
                    )

            evidence_ids = claim.get("evidence_ids", [])
            if not isinstance(evidence_ids, list):
                self.add(
                    "MALFORMED_CLAIM",
                    f"{path}.evidence_ids",
                    "evidence_ids must be a list.",
                )
                evidence_ids = []
            if status in EVIDENCE_REQUIRED_STATUSES and not evidence_ids:
                self.add(
                    "MISSING_EVIDENCE_REFERENCE",
                    f"{path}.evidence_ids",
                    f"Claim {cid!r} is {status!r} and must cite at least one evidence record.",
                )
            for eid in evidence_ids:
                if eid in self.evidence_ids:
                    self.cited_evidence.add(eid)
                else:
                    self.add(
                        "UNKNOWN_EVIDENCE_REFERENCE",
                        f"{path}.evidence_ids",
                        f"Claim {cid!r} cites unknown evidence {eid!r}.",
                    )

            if status == "inference":
                basis = claim.get("derived_from")
                if not isinstance(basis, list) or not basis:
                    self.add(
                        "INFERENCE_WITHOUT_BASIS",
                        f"{path}.derived_from",
                        f"Inference {cid!r} must list the claim ids it is derived from.",
                    )
                else:
                    for ref in basis:
                        if ref not in self.claim_ids or ref == cid:
                            self.add(
                                "UNKNOWN_CLAIM_REFERENCE",
                                f"{path}.derived_from",
                                f"Inference {cid!r} references unknown claim {ref!r}.",
                            )

            self.check_qualifiers(claim, path, scope_disease)
            self.check_review(claim.get("review"), f"{path}.review", cid)

    def check_qualifiers(
        self, claim: Mapping[str, Any], path: str, scope_disease: str | None
    ) -> None:
        qualifiers = claim.get("qualifiers")
        if not isinstance(qualifiers, Mapping):
            self.add(
                "MISSING_QUALIFIER",
                f"{path}.qualifiers",
                "Claim requires a qualifiers object.",
            )
            return
        disease = qualifiers.get("disease")
        disease_ok = self.check_disease_curie(disease, f"{path}.qualifiers.disease")

        genotype_dependent = claim.get("genotype_dependent") is True or (
            _normalize_predicate(claim["predicate"]) in GENOTYPE_DEPENDENT_PREDICATES
        )
        if genotype_dependent and not _nonempty_str(qualifiers.get("genotype")):
            self.add(
                "MISSING_QUALIFIER",
                f"{path}.qualifiers.genotype",
                "Genotype-dependent claim requires a genotype qualifier.",
            )

        transfer = qualifiers.get("context_transfer")
        if (
            disease_ok
            and scope_disease is not None
            and disease != scope_disease
            and not (isinstance(transfer, Mapping) and transfer)
        ):
            self.add(
                "CONTEXT_MISMATCH",
                f"{path}.qualifiers.disease",
                f"Claim disease {disease!r} differs from scope disease {scope_disease!r} "
                "without a declared context_transfer.",
            )

    def check_review(self, review: Any, path: str, cid: str) -> None:
        if review is None:
            return
        if not isinstance(review, Mapping):
            self.add("INVALID_REVIEW", path, "review must be an object.")
            return
        disposition = review.get("disposition")
        if disposition not in REVIEW_DISPOSITIONS:
            self.add(
                "INVALID_REVIEW",
                f"{path}.disposition",
                f"{disposition!r} is not one of {sorted(REVIEW_DISPOSITIONS)}.",
            )
            return
        kind = review.get("reviewer_kind")
        if disposition != "pending" and kind not in ACTOR_KINDS:
            self.add(
                "INVALID_REVIEW",
                f"{path}.reviewer_kind",
                f"reviewer_kind must be one of {sorted(ACTOR_KINDS)}, found {kind!r}.",
            )
            return
        if disposition == "accepted":
            if kind != "human":
                self.add(
                    "MODEL_ACCEPTANCE_NOT_ALLOWED",
                    f"{path}.disposition",
                    f"Claim {cid!r}: a {kind} reviewer cannot accept a claim. Model review and "
                    "deterministic checks do not establish scientific validity; escalate to a human.",
                )
            elif not _nonempty_str(review.get("reviewer_id")):
                self.add(
                    "MISSING_REVIEWER",
                    f"{path}.reviewer_id",
                    f"Claim {cid!r}: human acceptance must name the reviewer.",
                )

    # --- revision ---------------------------------------------------------

    def check_revision(self, doc: Mapping[str, Any]) -> None:
        revision = doc.get("revision")
        if not isinstance(revision, Mapping):
            self.add("MISSING_SECTION", "revision", "'revision' must be an object.")
            return
        for field in ("revision_id", "created_at", "producer", "parent_revision_id"):
            if field not in revision:
                self.add(
                    "MISSING_REVISION_FIELD",
                    f"revision.{field}",
                    f"Revision requires '{field}'.",
                )

        rid = revision.get("revision_id")
        if "revision_id" in revision and not _nonempty_str(rid):
            self.add(
                "INVALID_REVISION",
                "revision.revision_id",
                "revision_id must be a non-empty string.",
            )
        parent = revision.get("parent_revision_id")
        if "parent_revision_id" in revision and not (
            parent is None or _nonempty_str(parent)
        ):
            self.add(
                "INVALID_REVISION",
                "revision.parent_revision_id",
                "parent_revision_id must be a string, or null for a root revision.",
            )
        if _nonempty_str(rid) and parent == rid:
            self.add(
                "SELF_PARENT_REVISION",
                "revision.parent_revision_id",
                "A revision cannot be its own parent.",
            )
        created = revision.get("created_at")
        if "created_at" in revision and not _is_tz_timestamp(created):
            self.add(
                "INVALID_TIMESTAMP",
                "revision.created_at",
                f"{created!r} is not an ISO 8601 timestamp with a timezone.",
            )
        producer = revision.get("producer")
        if "producer" in revision and not (
            isinstance(producer, Mapping)
            and producer.get("kind") in ACTOR_KINDS
            and _nonempty_str(producer.get("id"))
        ):
            self.add(
                "INVALID_REVISION",
                "revision.producer",
                f"producer must be {{kind: one of {sorted(ACTOR_KINDS)}, id: string}}.",
            )
        declared = revision.get("content_digest")
        if declared is not None:
            actual = compute_content_digest(doc)
            if declared != actual:
                self.add(
                    "REVISION_DIGEST_MISMATCH",
                    "revision.content_digest",
                    f"Declared {declared!r}, computed {actual!r}; content changed after the revision was recorded.",
                )


# --- CLI ------------------------------------------------------------------


def _format_text(path: str, report: ValidationReport) -> str:
    lines = [
        f"{path}: {'OK' if report.ok else 'INVALID'} ({len(report.errors)} errors, {len(report.warnings)} warnings; profile={report.profile})"
    ]
    for issue in report.issues:
        lines.append(
            f"  {issue.severity.value.upper():7} {issue.code:36} {issue.path}: {issue.message}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 0 when valid, 1 when errors were found, 2 when the file cannot be read as JSON."""
    parser = argparse.ArgumentParser(
        prog="python -m biosciences_temporal.graph_refinement.validation",
        description="Deterministic structural/provenance validation for graph-refinement bundles. "
        "A pass does not establish scientific validity.",
    )
    parser.add_argument("path", help="JSON file to validate")
    parser.add_argument(
        "--profile", choices=[p.value for p in Profile], default=Profile.BUNDLE.value
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-nodes", type=int, default=None)
    parser.add_argument("--max-claims", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        doc = json.loads(Path(args.path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"{args.path}: cannot read JSON: {exc}", file=sys.stderr)
        return 2

    report = validate_graph(
        doc,
        profile=Profile(args.profile),
        max_nodes=args.max_nodes,
        max_claims=args.max_claims,
    )
    if args.format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(_format_text(args.path, report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
