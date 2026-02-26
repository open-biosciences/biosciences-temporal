"""
Validation agents - Phase 5: Validate.

Validates claims against source databases.
"""

from .base import AgentMetadata, AgentRunner
from .models import ValidationEvidence

# --- Agent Instructions ---

GENE_VALIDATION_INSTRUCTIONS = """
Independently verify the gene identifiers are correct and consistent.
Use hgnc_get_gene and check that cross-references match claimed values.
Report any discrepancies.
"""

DRUG_VALIDATION_INSTRUCTIONS = """
Verify the compound exists in ChEMBL.
Use chembl_get_compound with the ChEMBL ID from the claim.

Verify:
1. The compound ID exists
2. The compound name matches approximately

Report verified=True if compound exists, False otherwise.
Include the compound's max_phase in evidence if available.
"""

TRIAL_VALIDATION_INSTRUCTIONS = """
Verify the clinical trial exists in ClinicalTrials.gov.
Use clinicaltrials_get_trial with the NCT ID.
Confirm the trial exists and return key details.
"""

SYNTHETIC_LETHALITY_INSTRUCTIONS = """
Search for synthetic lethality evidence between the two genes.

IMPORTANT: When calling biogrid_get_interactions, always set max_results=100 to avoid context overflow.

1. Use biogrid_get_interactions with max_results=100 to find Negative Genetic interactions
2. Look for interactions between the two genes specifically
3. Report any PubMed IDs supporting the synthetic lethality claim

If no direct evidence is found, report verified=False with explanation.
"""

# --- Agent Runners ---

_gene_runner = AgentRunner(
    output_type=ValidationEvidence,
    instructions=GENE_VALIDATION_INSTRUCTIONS,
    name="validate_gene",
    metadata=AgentMetadata(
        phase="validate",
        action="gene",
        entity_type="gene",
        source="HGNC",
    ),
)

_drug_runner = AgentRunner(
    output_type=ValidationEvidence,
    instructions=DRUG_VALIDATION_INSTRUCTIONS,
    name="validate_drug",
    metadata=AgentMetadata(
        phase="validate",
        action="drug",
        entity_type="compound",
        source="ChEMBL",
    ),
)

_trial_runner = AgentRunner(
    output_type=ValidationEvidence,
    instructions=TRIAL_VALIDATION_INSTRUCTIONS,
    name="validate_trial",
    metadata=AgentMetadata(
        phase="validate",
        action="trial",
        entity_type="trial",
        source="ClinicalTrials.gov",
    ),
)

_sl_runner = AgentRunner(
    output_type=ValidationEvidence,
    instructions=SYNTHETIC_LETHALITY_INSTRUCTIONS,
    name="validate_sl",
    metadata=AgentMetadata(
        phase="validate",
        action="sl",
        entity_type="gene_pair",
        source="BioGRID",
    ),
)


# --- Validation Functions ---

async def validate_gene(claim: str, cq_id: str = "cq14") -> ValidationEvidence:
    """Validate gene identifiers against HGNC.

    Args:
        claim: Gene claim to validate (e.g., "TP53: HGNC=HGNC:11998, Entrez=7157")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        ValidationEvidence with verification result.
    """
    return await _gene_runner.run(f"Validate: {claim}", cq_id=cq_id)


async def validate_drug(claim: str, cq_id: str = "cq14") -> ValidationEvidence:
    """Validate drug/compound against ChEMBL.

    Args:
        claim: Drug claim to validate (e.g., "CHEMBL:185 - Fluorouracil")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        ValidationEvidence with verification result.
    """
    return await _drug_runner.run(f"Validate compound: {claim}", cq_id=cq_id)


async def validate_trial(nct_id: str, cq_id: str = "cq14") -> ValidationEvidence:
    """Validate clinical trial exists in ClinicalTrials.gov.

    Args:
        nct_id: NCT ID to validate (e.g., "NCT:00461032")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        ValidationEvidence with verification result.
    """
    return await _trial_runner.run(f"Validate clinical trial: {nct_id}", cq_id=cq_id)


async def validate_synthetic_lethality(
    gene_a: str, gene_b: str, cq_id: str = "cq14"
) -> ValidationEvidence:
    """Validate synthetic lethality claim between two genes.

    Args:
        gene_a: First gene in the pair (e.g., "TP53")
        gene_b: Second gene in the pair (e.g., "TYMS")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        ValidationEvidence with verification result and PubMed references.
    """
    return await _sl_runner.run(
        f"Check synthetic lethality between {gene_a} and {gene_b}",
        cq_id=cq_id,
    )
