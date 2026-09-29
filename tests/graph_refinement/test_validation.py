"""Unit tests for the deterministic graph-refinement validator.

No network, no LLM, no Temporal server. The sl-system-approach fixtures are
structural test inputs, not scientific ground truth; see fixtures/README.md.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from biosciences_temporal.graph_refinement.validation import (
    SCHEMA_VERSION,
    Profile,
    Severity,
    compute_content_digest,
    main,
    validate_graph,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures"
SL_DIR = FIXTURES / "sl_system_approach"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def bundle() -> dict[str, Any]:
    return _load(FIXTURES / "synthetic" / "valid_bundle.json")


def _error_codes(doc: dict[str, Any], **kwargs: Any) -> set[str]:
    report = validate_graph(doc, **kwargs)
    return {i.code for i in report.issues if i.severity is Severity.ERROR}


def _claim(doc: dict[str, Any], claim_id: str) -> dict[str, Any]:
    return next(c for c in doc["claims"] if c["claim_id"] == claim_id)


# --- Baseline -------------------------------------------------------------


def test_synthetic_bundle_has_no_errors(bundle: dict[str, Any]) -> None:
    report = validate_graph(bundle)
    assert report.ok, [i.model_dump() for i in report.errors]


def test_declared_unresolved_node_is_a_warning_not_an_error(
    bundle: dict[str, Any],
) -> None:
    report = validate_graph(bundle)
    warnings = {
        (i.code, i.path) for i in report.issues if i.severity is Severity.WARNING
    }
    assert ("UNRESOLVED_IDENTIFIER", "nodes[4].id") in warnings


def test_report_is_deterministic(bundle: dict[str, Any]) -> None:
    first = validate_graph(bundle).model_dump()
    second = validate_graph(copy.deepcopy(bundle)).model_dump()
    assert first == second


# --- Structure and identifiers -------------------------------------------


def test_missing_sections_are_reported() -> None:
    codes = _error_codes({"schema_version": SCHEMA_VERSION})
    assert "MISSING_SECTION" in codes


def test_unsupported_schema_version(bundle: dict[str, Any]) -> None:
    bundle["schema_version"] = "graph-refinement-bundle/9.9"
    assert "UNSUPPORTED_SCHEMA_VERSION" in _error_codes(bundle)


def test_duplicate_node_id(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "HGNC:9999901", "type": "Gene", "label": "dup"})
    assert "DUPLICATE_NODE_ID" in _error_codes(bundle)


def test_duplicate_node_id_after_normalization(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "hgnc:9999901", "type": "Gene", "label": "dup"})
    assert "DUPLICATE_NODE_ID_NORMALIZED" in _error_codes(bundle)


def test_bare_identifier_is_not_a_curie(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "NCT01294306", "type": "Trial", "label": "bare"})
    assert "INVALID_CURIE" in _error_codes(bundle)


def test_known_prefix_with_malformed_local_id(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "NCT:123", "type": "Trial", "label": "short"})
    assert "CURIE_PATTERN_MISMATCH" in _error_codes(bundle)


def test_bare_ensembl_gene_id_is_accepted(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "ENSG00000000001", "type": "Gene", "label": "ens"})
    assert not _error_codes(bundle)


def test_undeclared_placeholder_identifier_is_an_error(bundle: dict[str, Any]) -> None:
    del bundle["nodes"][4]["id_status"]
    assert "UNRESOLVED_IDENTIFIER" in _error_codes(bundle)


def test_local_concept_is_a_warning(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append(
        {
            "id": "FRAMEWORK:example",
            "type": "Framework",
            "label": "f",
            "id_status": "local_concept",
        }
    )
    report = validate_graph(bundle)
    assert report.ok
    assert "LOCAL_IDENTIFIER" in {i.code for i in report.issues}


def test_dangling_edge_endpoint(bundle: dict[str, Any]) -> None:
    bundle["edges"].append(
        {"source": "CHEMBL:9999901", "target": "HGNC:9999999", "type": "inhibits"}
    )
    assert "DANGLING_EDGE_ENDPOINT" in _error_codes(bundle)


def test_malformed_edge(bundle: dict[str, Any]) -> None:
    bundle["edges"].append({"source": "CHEMBL:9999901", "type": "inhibits"})
    assert "MALFORMED_EDGE" in _error_codes(bundle)


def test_duplicate_edge_is_a_warning(bundle: dict[str, Any]) -> None:
    bundle["edges"].append(dict(bundle["edges"][0]))
    report = validate_graph(bundle)
    assert report.ok
    assert "DUPLICATE_EDGE" in {i.code for i in report.issues}


def test_metadata_count_mismatch(bundle: dict[str, Any]) -> None:
    bundle["metadata"] = {"node_count": 5, "edge_count": 7, "gene_count": 2}
    report = validate_graph(bundle)
    mismatches = [i for i in report.errors if i.code == "COUNT_MISMATCH"]
    assert [i.path for i in mismatches] == ["metadata.edge_count"]


# --- Claims and evidence --------------------------------------------------


def test_supported_claim_without_evidence(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["evidence_ids"] = []
    assert "MISSING_EVIDENCE_REFERENCE" in _error_codes(bundle)


def test_claim_cites_unknown_evidence(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["evidence_ids"] = ["ev-404"]
    assert "UNKNOWN_EVIDENCE_REFERENCE" in _error_codes(bundle)


@pytest.mark.parametrize("status", ["validated", "verified", "true", "accepted"])
def test_truth_like_status_is_rejected(bundle: dict[str, Any], status: str) -> None:
    _claim(bundle, "c-1")["status"] = status
    assert "INVALID_CLAIM_STATUS" in _error_codes(bundle)


def test_duplicate_claim_id(bundle: dict[str, Any]) -> None:
    bundle["claims"].append(copy.deepcopy(_claim(bundle, "c-1")))
    assert "DUPLICATE_CLAIM_ID" in _error_codes(bundle)


def test_claim_endpoint_must_be_in_graph(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["object"] = "HGNC:9999999"
    assert "CLAIM_ENDPOINT_NOT_IN_GRAPH" in _error_codes(bundle)


def test_inference_requires_known_basis(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-3")["derived_from"] = ["c-404"]
    assert "UNKNOWN_CLAIM_REFERENCE" in _error_codes(bundle)
    _claim(bundle, "c-3")["derived_from"] = []
    assert "INFERENCE_WITHOUT_BASIS" in _error_codes(bundle)


def test_supported_claim_on_unresolved_entity(bundle: dict[str, Any]) -> None:
    claim = _claim(bundle, "c-1")
    claim["subject"] = "COMPOUND:drug-z"
    assert "SUPPORTED_CLAIM_ON_UNRESOLVED_ENTITY" in _error_codes(bundle)


def test_hypothesis_may_reference_unresolved_entity(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-2")["subject"] = "COMPOUND:drug-z"
    assert not _error_codes(bundle)


def test_missing_disease_qualifier(bundle: dict[str, Any]) -> None:
    del _claim(bundle, "c-1")["qualifiers"]["disease"]
    assert "MISSING_QUALIFIER" in _error_codes(bundle)


def test_disease_qualifier_must_be_a_disease_curie(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["qualifiers"]["disease"] = "lung cancer"
    assert "INVALID_QUALIFIER" in _error_codes(bundle)


def test_genotype_dependent_predicate_requires_genotype(bundle: dict[str, Any]) -> None:
    del _claim(bundle, "c-2")["qualifiers"]["genotype"]
    assert "MISSING_QUALIFIER" in _error_codes(bundle)


def test_genotype_dependent_flag_requires_genotype(bundle: dict[str, Any]) -> None:
    del _claim(bundle, "c-3")["qualifiers"]["genotype"]
    assert "MISSING_QUALIFIER" in _error_codes(bundle)


def test_scope_disease_is_required(bundle: dict[str, Any]) -> None:
    del bundle["scope"]["disease"]
    assert "MISSING_QUALIFIER" in _error_codes(bundle)


def test_context_transfer_must_be_declared(bundle: dict[str, Any]) -> None:
    bundle["nodes"].append({"id": "MONDO:9999902", "type": "Disease", "label": "OTHER"})
    _claim(bundle, "c-1")["qualifiers"]["disease"] = "MONDO:9999902"
    assert "CONTEXT_MISMATCH" in _error_codes(bundle)
    _claim(bundle, "c-1")["qualifiers"]["context_transfer"] = {
        "from": "MONDO:9999902",
        "rationale": "declared for review",
    }
    assert "CONTEXT_MISMATCH" not in _error_codes(bundle)


def test_model_reviewer_cannot_accept(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["review"] = {
        "disposition": "accepted",
        "reviewer_kind": "model",
        "reviewer_id": "synthetic-reviewer",
    }
    assert "MODEL_ACCEPTANCE_NOT_ALLOWED" in _error_codes(bundle)


def test_human_acceptance_requires_reviewer_identity(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["review"] = {
        "disposition": "accepted",
        "reviewer_kind": "human",
    }
    assert "MISSING_REVIEWER" in _error_codes(bundle)
    _claim(bundle, "c-1")["review"]["reviewer_id"] = "reviewer-1"
    assert not _error_codes(bundle)


def test_invalid_review_disposition(bundle: dict[str, Any]) -> None:
    _claim(bundle, "c-1")["review"]["disposition"] = "pass"
    assert "INVALID_REVIEW" in _error_codes(bundle)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("retrieved_at", None, "MISSING_PROVENANCE_FIELD"),
        ("record_id", "", "MISSING_PROVENANCE_FIELD"),
        ("retrieved_at", "yesterday", "INVALID_TIMESTAMP"),
        ("retrieved_at", "2026-09-28T12:00:00", "INVALID_TIMESTAMP"),
        ("content_digest", "md5:abc", "INVALID_DIGEST"),
    ],
)
def test_evidence_provenance(
    bundle: dict[str, Any], field: str, value: Any, code: str
) -> None:
    if value is None:
        del bundle["evidence"][0][field]
    else:
        bundle["evidence"][0][field] = value
    assert code in _error_codes(bundle)


def test_duplicate_evidence_id(bundle: dict[str, Any]) -> None:
    bundle["evidence"].append(copy.deepcopy(bundle["evidence"][0]))
    assert "DUPLICATE_EVIDENCE_ID" in _error_codes(bundle)


def test_unused_evidence_and_unclaimed_edge_are_warnings(
    bundle: dict[str, Any],
) -> None:
    bundle["evidence"].append(
        {**copy.deepcopy(bundle["evidence"][0]), "evidence_id": "ev-unused"}
    )
    bundle["edges"].append(
        {"source": "HGNC:9999902", "target": "HGNC:9999901", "type": "binds"}
    )
    report = validate_graph(bundle)
    assert report.ok
    assert {"UNUSED_EVIDENCE", "EDGE_WITHOUT_CLAIM"} <= {i.code for i in report.issues}


# --- Revision metadata ----------------------------------------------------


@pytest.mark.parametrize(
    "field", ["revision_id", "created_at", "producer", "parent_revision_id"]
)
def test_revision_fields_required(bundle: dict[str, Any], field: str) -> None:
    del bundle["revision"][field]
    assert "MISSING_REVISION_FIELD" in _error_codes(bundle)


def test_root_revision_has_explicit_null_parent(bundle: dict[str, Any]) -> None:
    bundle["revision"]["parent_revision_id"] = None
    assert not _error_codes(bundle)


def test_revision_cannot_be_its_own_parent(bundle: dict[str, Any]) -> None:
    bundle["revision"]["parent_revision_id"] = bundle["revision"]["revision_id"]
    assert "SELF_PARENT_REVISION" in _error_codes(bundle)


def test_revision_producer_kind(bundle: dict[str, Any]) -> None:
    bundle["revision"]["producer"] = {"kind": "oracle", "id": "x"}
    assert "INVALID_REVISION" in _error_codes(bundle)


def test_revision_content_digest(bundle: dict[str, Any]) -> None:
    bundle["revision"]["content_digest"] = compute_content_digest(bundle)
    assert not _error_codes(bundle)
    _claim(bundle, "c-1")["status"] = "hypothesis"
    assert "REVISION_DIGEST_MISMATCH" in _error_codes(bundle)


def test_content_digest_ignores_revision_block_and_key_order(
    bundle: dict[str, Any],
) -> None:
    digest = compute_content_digest(bundle)
    reordered = json.loads(json.dumps(bundle, sort_keys=True))
    reordered["revision"]["created_at"] = "2027-01-01T00:00:00Z"
    assert compute_content_digest(reordered) == digest
    assert digest.startswith("sha256:")


# --- Budgets --------------------------------------------------------------


def test_optional_budgets(bundle: dict[str, Any]) -> None:
    assert not _error_codes(bundle, max_nodes=5, max_claims=3)
    codes = _error_codes(bundle, max_nodes=4, max_claims=2)
    assert "BUDGET_EXCEEDED" in codes


# --- sl-system-approach fixtures (structural edge cases only) -------------


def _codes_at(path: Path, profile: Profile) -> list[tuple[str, str]]:
    report = validate_graph(_load(path), profile=profile)
    return [(i.code, i.path) for i in report.errors]


def test_initial_graph_metadata_overstates_edges() -> None:
    found = _codes_at(
        SL_DIR / "sprime-sl-lung-cancer-knowledge-graph.json", Profile.STRUCTURAL
    )
    assert ("COUNT_MISMATCH", "metadata.total_edges") in found


def test_v2_graph_has_dangling_rigosertib_edge_and_count_drift() -> None:
    report = validate_graph(
        _load(SL_DIR / "sprime-sl-lung-cancer-knowledge-graph-v2.json"),
        profile=Profile.STRUCTURAL,
    )
    dangling = [i for i in report.errors if i.code == "DANGLING_EDGE_ENDPOINT"]
    assert len(dangling) == 1
    assert "HGNC:9077" in dangling[0].message
    assert "COMPOUND:rigosertib" in dangling[0].message
    count_paths = {i.path for i in report.errors if i.code == "COUNT_MISMATCH"}
    assert {"metadata.total_edges", "metadata.total_gene_nodes"} <= count_paths


def test_v2_graph_uses_bare_trial_ids_and_undeclared_placeholders() -> None:
    found = _codes_at(
        SL_DIR / "sprime-sl-lung-cancer-knowledge-graph-v2.json", Profile.STRUCTURAL
    )
    codes = {code for code, _ in found}
    assert {"INVALID_CURIE", "UNRESOLVED_IDENTIFIER"} <= codes


def test_systemic_graph_is_closed_but_not_a_refinement_bundle() -> None:
    path = SL_DIR / "sprime-sl-systemic-fragility-knowledge-graph.json"
    structural = {code for code, _ in _codes_at(path, Profile.STRUCTURAL)}
    assert "DANGLING_EDGE_ENDPOINT" not in structural
    assert "COUNT_MISMATCH" not in structural
    # Local placeholders (COMPOUND:, FRAMEWORK:) are not declared as unresolved.
    assert "UNRESOLVED_IDENTIFIER" in structural
    bundle_codes = {code for code, _ in _codes_at(path, Profile.BUNDLE)}
    assert "MISSING_SECTION" in bundle_codes


@pytest.mark.parametrize(
    "name",
    [
        "sprime-sl-lung-cancer-knowledge-graph.json",
        "sprime-sl-lung-cancer-knowledge-graph-v2.json",
        "sprime-sl-systemic-fragility-knowledge-graph.json",
    ],
)
def test_no_sl_fixture_passes_as_a_refinement_bundle(name: str) -> None:
    assert not validate_graph(_load(SL_DIR / name)).ok


# --- CLI ------------------------------------------------------------------


def test_cli_exit_codes_and_json_output(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    good = FIXTURES / "synthetic" / "valid_bundle.json"
    assert main([str(good)]) == 0
    capsys.readouterr()

    bad = SL_DIR / "sprime-sl-lung-cancer-knowledge-graph-v2.json"
    assert main([str(bad), "--profile", "structural", "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(i["code"] == "DANGLING_EDGE_ENDPOINT" for i in payload["issues"])

    not_json = tmp_path / "broken.json"
    not_json.write_text("{", encoding="utf-8")
    assert main([str(not_json)]) == 2
