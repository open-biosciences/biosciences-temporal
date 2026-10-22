"""
Shared Pydantic models for CQ14 agents.

These models define the structured outputs from each phase of the
Fuzzy-to-Fact protocol.
"""

import re
from typing import Optional

from pydantic import BaseModel, field_validator


# --- Phase 1: Anchor ---

_HGNC_CURIE = re.compile(r"^HGNC:\d+$")


class GeneInfo(BaseModel):
    """Resolved gene information from HGNC."""
    hgnc_id: str
    symbol: str
    name: str
    entrez_id: Optional[str] = None
    uniprot_id: Optional[str] = None
    ensembl_id: Optional[str] = None
    location: Optional[str] = None  # cytogenetic band, e.g. "17p13.1" (required by the pre-emit gate)

    @field_validator("hgnc_id")
    @classmethod
    def validate_hgnc_id(cls, v: str) -> str:
        # A canonical CURIE only: a sentinel such as "NOT_FOUND" must fail
        # validation, not read as a successful resolution (AGE-743). A
        # validator, not Field(pattern=...), keeps the pattern out of the
        # JSON schema sent to the model.
        if not _HGNC_CURIE.match(v):
            raise ValueError(f"hgnc_id must be an HGNC CURIE like 'HGNC:11998', got {v!r}")
        return v


# --- Phase 2: Enrich ---

class ProteinFunction(BaseModel):
    """Protein functional context from UniProt."""
    uniprot_id: str
    function_summary: str
    keywords: list[str] = []


# --- Phase 3: Expand ---

class GeneInteraction(BaseModel):
    """Gene-gene or protein-protein interaction."""
    partner_gene: str
    interaction_type: str  # physical, genetic, negative_genetic
    evidence_source: str  # STRING, BioGRID
    score: Optional[float] = None
    pubmed_id: Optional[str] = None


# --- Phase 4: Traverse ---

class DrugCandidate(BaseModel):
    """Drug candidate from ChEMBL."""
    chembl_id: str
    name: str
    target_name: str
    mechanism: str  # INHIBITOR, AGONIST, etc.
    max_phase: int  # 0-4, 4 = approved


class ClinicalTrial(BaseModel):
    """Clinical trial from ClinicalTrials.gov."""
    nct_id: str
    title: str
    phase: str
    status: str
    conditions: list[str] = []
    interventions: list[str] = []


# --- Phase 5: Validate ---

class ValidationEvidence(BaseModel):
    """Validation evidence for a claim."""
    claim: str
    verified: bool
    evidence_source: str
    evidence_details: str
    pubmed_ids: list[str] = []
