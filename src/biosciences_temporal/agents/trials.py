"""
Clinical trials agent - Phase 4b: Traverse (Trials).

Searches clinical trials for drugs using ClinicalTrials.gov.
"""

from .base import AgentMetadata, AgentRunner
from .models import ClinicalTrial

INSTRUCTIONS = """
You search clinical trials for drugs or interventions.

WORKFLOW:
1. Use clinicaltrials_search_trials(query="DRUG_NAME", condition="DISEASE")

IMPORTANT:
- The query parameter should contain the DRUG NAME (e.g., "pemetrexed")
- NOT the mechanism (e.g., "TYMS inhibitor")
- Filter by condition if specified
- Return NCT IDs in CURIE format (e.g., "NCT:00461032")
"""

_runner = AgentRunner(
    output_type=list[ClinicalTrial],
    instructions=INSTRUCTIONS,
    name="traverse_trials",
    metadata=AgentMetadata(
        phase="traverse",
        action="trials",
        entity_type="trial",
        source="ClinicalTrials.gov",
    ),
)


async def search_trials(
    drug_name: str, condition: str = "cancer", cq_id: str = "cq14"
) -> list[ClinicalTrial]:
    """Search clinical trials for a drug.

    Args:
        drug_name: Drug name to search for (e.g., "pemetrexed", "fluorouracil")
        condition: Disease condition to filter by (default: "cancer")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        List of matching clinical trials.
    """
    return await _runner.run(
        f"Search for clinical trials with {drug_name} for {condition}",
        cq_id=cq_id,
    )
