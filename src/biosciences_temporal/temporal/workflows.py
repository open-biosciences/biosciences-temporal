"""
CQ14 Temporal Workflow definition.

Orchestrates the 5-phase Fuzzy-to-Fact protocol with durable execution.
"""

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from temporalio import workflow

# Pass through non-deterministic imports (pydantic, anyio, etc.)
with workflow.unsafe.imports_passed_through():
    from ..config import LONG_ACTIVITY_CONFIG, SHORT_ACTIVITY_CONFIG


@dataclass
class CQ14Input:
    """Input for CQ14 workflow."""
    gene_a: str = "TP53"
    gene_b: str = "TYMS"
    target_name: str = "thymidylate synthase"
    condition: str = "cancer"


@dataclass
class CQ14Result:
    """Complete result of CQ14 workflow."""
    gene_a_resolution: Optional[dict] = None
    gene_b_resolution: Optional[dict] = None
    gene_a_protein: Optional[dict] = None
    gene_b_protein: Optional[dict] = None
    gene_b_interactions: Optional[dict] = None
    drugs: list = field(default_factory=list)
    trials: list = field(default_factory=list)
    validations: list = field(default_factory=list)


@workflow.defn
class CQ14Workflow:
    """CQ14 workflow with durable execution via Temporal.

    Orchestrates the 5-phase Fuzzy-to-Fact protocol:
    1. Anchor - Resolve gene symbols
    2. Enrich - Get protein context
    3. Expand - Find interactions
    4. Traverse - Find drugs and trials
    5. Validate - Verify claims
    """

    @workflow.run
    async def run(self, input_json: str) -> str:
        """Execute the CQ14 validation workflow."""
        input_dict = json.loads(input_json)
        input_data = CQ14Input(**input_dict)
        result = CQ14Result()

        # Phase 1: Anchor - Resolve both genes in parallel
        workflow.logger.info(f"Phase 1: Anchoring {input_data.gene_a} and {input_data.gene_b}")

        gene_a_task = workflow.execute_activity(
            "resolve_gene",
            args=[input_data.gene_a],
            **SHORT_ACTIVITY_CONFIG,
        )
        gene_b_task = workflow.execute_activity(
            "resolve_gene",
            args=[input_data.gene_b],
            **SHORT_ACTIVITY_CONFIG,
        )

        gene_results = await asyncio.gather(gene_a_task, gene_b_task, return_exceptions=True)

        if not isinstance(gene_results[0], Exception):
            result.gene_a_resolution = gene_results[0]
        if not isinstance(gene_results[1], Exception):
            result.gene_b_resolution = gene_results[1]

        # Phase 2: Enrich - Get protein context
        workflow.logger.info("Phase 2: Enriching protein context")

        enrich_tasks = []
        if result.gene_a_resolution and result.gene_a_resolution.get("uniprot_id"):
            enrich_tasks.append(
                workflow.execute_activity(
                    "enrich_protein",
                    args=[result.gene_a_resolution["uniprot_id"]],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )
        if result.gene_b_resolution and result.gene_b_resolution.get("uniprot_id"):
            enrich_tasks.append(
                workflow.execute_activity(
                    "enrich_protein",
                    args=[result.gene_b_resolution["uniprot_id"]],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )

        if enrich_tasks:
            enrich_results = await asyncio.gather(*enrich_tasks, return_exceptions=True)
            if len(enrich_results) > 0 and not isinstance(enrich_results[0], Exception):
                result.gene_a_protein = enrich_results[0]
            if len(enrich_results) > 1 and not isinstance(enrich_results[1], Exception):
                result.gene_b_protein = enrich_results[1]

        # Phase 3: Expand - Get interactions for target gene
        workflow.logger.info("Phase 3: Expanding interaction network")

        try:
            result.gene_b_interactions = await workflow.execute_activity(
                "expand_interactions",
                args=[input_data.gene_b],
                **LONG_ACTIVITY_CONFIG,
            )
        except Exception as e:
            workflow.logger.warning(f"Interaction expansion failed: {e}")

        # Phase 4a: Traverse - Find drugs targeting the protein
        workflow.logger.info("Phase 4a: Finding drugs targeting the protein")

        try:
            result.drugs = await workflow.execute_activity(
                "find_drugs",
                args=[input_data.target_name],
                **LONG_ACTIVITY_CONFIG,
            )
        except Exception as e:
            workflow.logger.warning(f"Drug discovery failed: {e}")

        # Phase 4b: Traverse - Search clinical trials using discovered drug names
        workflow.logger.info("Phase 4b: Searching clinical trials")

        if result.drugs:
            # Use first discovered drug name for trial search
            drug_name = result.drugs[0].get("name", input_data.target_name)
            workflow.logger.info(f"Searching trials for drug: {drug_name}")
        else:
            # Fallback to target name if no drugs found
            drug_name = input_data.target_name
            workflow.logger.warning(f"No drugs found, searching trials for: {drug_name}")

        try:
            result.trials = await workflow.execute_activity(
                "search_trials",
                args=[drug_name, input_data.condition],
                **LONG_ACTIVITY_CONFIG,
            )
        except Exception as e:
            workflow.logger.warning(f"Trial search failed: {e}")

        # Phase 5: Validate - Run validators in parallel
        workflow.logger.info("Phase 5: Running validation agents")

        validation_tasks = []

        # Validate gene A
        if result.gene_a_resolution:
            claim = (
                f"{input_data.gene_a}: HGNC={result.gene_a_resolution.get('hgnc_id')}, "
                f"Entrez={result.gene_a_resolution.get('entrez_id', 'N/A')}"
            )
            validation_tasks.append(
                workflow.execute_activity(
                    "validate_gene",
                    args=[claim],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )

        # Validate gene B
        if result.gene_b_resolution:
            claim = (
                f"{input_data.gene_b}: HGNC={result.gene_b_resolution.get('hgnc_id')}, "
                f"Entrez={result.gene_b_resolution.get('entrez_id', 'N/A')}"
            )
            validation_tasks.append(
                workflow.execute_activity(
                    "validate_gene",
                    args=[claim],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )

        # Validate drug compounds (top 2)
        for drug in result.drugs[:2]:
            claim = (
                f"{drug.get('chembl_id')} - {drug.get('name')}, "
                f"target={drug.get('target_name')}, mechanism={drug.get('mechanism')}"
            )
            validation_tasks.append(
                workflow.execute_activity(
                    "validate_mechanism",
                    args=[claim],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )

        # Validate first trial
        if result.trials:
            validation_tasks.append(
                workflow.execute_activity(
                    "validate_trial",
                    args=[result.trials[0].get("nct_id", "")],
                    **SHORT_ACTIVITY_CONFIG,
                )
            )

        # Validate synthetic lethality
        validation_tasks.append(
            workflow.execute_activity(
                "validate_synthetic_lethality",
                args=[input_data.gene_a, input_data.gene_b],
                **SHORT_ACTIVITY_CONFIG,
            )
        )

        validation_results = await asyncio.gather(*validation_tasks, return_exceptions=True)
        result.validations = [
            v for v in validation_results if not isinstance(v, Exception)
        ]

        workflow.logger.info("Workflow complete")
        return json.dumps(asdict(result), indent=2)
