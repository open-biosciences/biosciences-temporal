"""
CQ14 Orchestrator - Standalone PydanticAI workflow.

Coordinates the 5-phase Fuzzy-to-Fact protocol for validating
synthetic lethality claims. Can run without Temporal.

Usage:
    from src.biosciences_temporal.agents.cq14 import CQ14Orchestrator

    orchestrator = CQ14Orchestrator(gene_a="TP53", gene_b="TYMS")
    result = await orchestrator.run()
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    ClinicalTrial,
    DrugCandidate,
    GeneInfo,
    GeneInteraction,
    ProteinFunction,
    ValidationEvidence,
)
from .resolve import resolve_gene
from .enrich import enrich_protein
from .expand import expand_interactions
from .drugs import find_drugs
from .trials import search_trials
from .validate import validate_gene, validate_drug, validate_synthetic_lethality


@dataclass
class CQ14Result:
    """Complete CQ14 workflow result."""

    # Phase 1: Anchor
    gene_a: Optional[GeneInfo] = None
    gene_b: Optional[GeneInfo] = None

    # Phase 2: Enrich
    gene_a_function: Optional[ProteinFunction] = None
    gene_b_function: Optional[ProteinFunction] = None

    # Phase 3: Expand
    interactions: list[GeneInteraction] = field(default_factory=list)

    # Phase 4: Traverse
    drugs: list[DrugCandidate] = field(default_factory=list)
    trials: list[ClinicalTrial] = field(default_factory=list)

    # Phase 5: Validate
    validations: list[ValidationEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "gene_a": self.gene_a.model_dump() if self.gene_a else None,
            "gene_b": self.gene_b.model_dump() if self.gene_b else None,
            "gene_a_function": self.gene_a_function.model_dump() if self.gene_a_function else None,
            "gene_b_function": self.gene_b_function.model_dump() if self.gene_b_function else None,
            "interactions": [i.model_dump() for i in self.interactions],
            "drugs": [d.model_dump() for d in self.drugs],
            "trials": [t.model_dump() for t in self.trials],
            "validations": [v.model_dump() for v in self.validations],
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class CQ14Orchestrator:
    """
    Orchestrates the 5-phase Fuzzy-to-Fact protocol for CQ14.

    This class coordinates multiple specialized agents to validate
    synthetic lethality claims. It can run standalone without Temporal,
    or be wrapped by Temporal activities for durable execution.
    """

    def __init__(self, gene_a: str = "TP53", gene_b: str = "TYMS"):
        self.gene_a = gene_a
        self.gene_b = gene_b
        self.result = CQ14Result()

    async def run(self) -> CQ14Result:
        """Execute the complete CQ14 workflow."""
        print(f"\n{'='*60}")
        print(f"CQ14 Synthetic Lethality Validation: {self.gene_a}-{self.gene_b}")
        print(f"{'='*60}")

        await self.phase1_anchor()
        await self.phase2_enrich()
        await self.phase3_expand()
        await self.phase4_traverse()
        await self.phase5_validate()

        return self.result

    async def phase1_anchor(self):
        """Phase 1: Resolve gene symbols to canonical identifiers."""
        print("\n--- Phase 1: Anchor ---")

        print(f"Resolving {self.gene_a}...")
        self.result.gene_a = await resolve_gene(self.gene_a)
        print(f"  → {self.result.gene_a.hgnc_id}: {self.result.gene_a.name}")

        print(f"Resolving {self.gene_b}...")
        self.result.gene_b = await resolve_gene(self.gene_b)
        print(f"  → {self.result.gene_b.hgnc_id}: {self.result.gene_b.name}")

    async def phase2_enrich(self):
        """Phase 2: Get protein functional context."""
        print("\n--- Phase 2: Enrich ---")

        if self.result.gene_a and self.result.gene_a.uniprot_id:
            print(f"Getting protein context for {self.gene_a}...")
            self.result.gene_a_function = await enrich_protein(self.result.gene_a.uniprot_id)
            print(f"  → {self.result.gene_a_function.function_summary[:100]}...")

        if self.result.gene_b and self.result.gene_b.uniprot_id:
            print(f"Getting protein context for {self.gene_b}...")
            self.result.gene_b_function = await enrich_protein(self.result.gene_b.uniprot_id)
            print(f"  → {self.result.gene_b_function.function_summary[:100]}...")

    async def phase3_expand(self):
        """Phase 3: Find protein-protein and genetic interactions."""
        print("\n--- Phase 3: Expand ---")

        print(f"Finding interactions for {self.gene_b}...")
        self.result.interactions = await expand_interactions(self.gene_b)
        print(f"  → Found {len(self.result.interactions)} interactions")

        for interaction in self.result.interactions[:5]:
            print(f"    - {interaction.partner_gene}: {interaction.interaction_type} ({interaction.evidence_source})")

    async def phase4_traverse(self):
        """Phase 4: Find drugs and clinical trials."""
        print("\n--- Phase 4: Traverse ---")

        # Phase 4a: Find drugs
        target_name = "thymidylate synthase" if self.gene_b == "TYMS" else self.gene_b
        print(f"Finding drugs targeting {target_name}...")
        self.result.drugs = await find_drugs(target_name)
        print(f"  → Found {len(self.result.drugs)} drugs")

        for drug in self.result.drugs[:3]:
            print(f"    - {drug.name} ({drug.chembl_id}): {drug.mechanism}, Phase {drug.max_phase}")

        # Phase 4b: Find trials using discovered drug names
        if self.result.drugs:
            drug_name = self.result.drugs[0].name
            print(f"Finding trials for {drug_name}...")
            self.result.trials = await search_trials(drug_name)
            print(f"  → Found {len(self.result.trials)} trials")

            for trial in self.result.trials[:3]:
                print(f"    - {trial.nct_id}: {trial.title[:50]}... ({trial.phase})")
        else:
            print("  No drugs found, skipping trial search")

    async def phase5_validate(self):
        """Phase 5: Validate claims against source databases."""
        print("\n--- Phase 5: Validate ---")

        # Validate synthetic lethality claim
        print(f"Validating synthetic lethality: {self.gene_a}-{self.gene_b}...")
        sl_result = await validate_synthetic_lethality(self.gene_a, self.gene_b)
        self.result.validations.append(sl_result)
        status = "✓" if sl_result.verified else "✗"
        print(f"  {status} {sl_result.claim}")

        # Validate first drug
        if self.result.drugs:
            drug = self.result.drugs[0]
            print(f"Validating drug: {drug.name}...")
            drug_result = await validate_drug(
                f"{drug.name} ({drug.chembl_id}) targets {drug.target_name}"
            )
            self.result.validations.append(drug_result)
            status = "✓" if drug_result.verified else "✗"
            print(f"  {status} {drug_result.claim}")
