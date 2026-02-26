"""
Drug discovery agent - Phase 4a: Traverse (Drugs).

Finds drugs targeting a protein using ChEMBL.
"""

from .base import AgentMetadata, AgentRunner
from .models import DrugCandidate

INSTRUCTIONS = """
You find drugs targeting a protein using ChEMBL.

WORKFLOW:
1. Use chembl_search_compounds(query="TARGET_NAME inhibitor") or
   chembl_search_compounds(query="DRUG_NAME")
2. Use chembl_get_compound(chembl_id="CHEMBL:NNNNN") for details

IMPORTANT:
- Search by target name (e.g., "thymidylate synthase inhibitor")
- Prioritize Phase 4 (approved) drugs
- Return ChEMBL IDs in CURIE format (e.g., "CHEMBL:185")
- Include mechanism of action (INHIBITOR, AGONIST, etc.)
"""

_runner = AgentRunner(
    output_type=list[DrugCandidate],
    instructions=INSTRUCTIONS,
    name="traverse_drugs",
    metadata=AgentMetadata(
        phase="traverse",
        action="drugs",
        entity_type="compound",
        source="ChEMBL",
    ),
)


async def find_drugs(target_name: str, cq_id: str = "cq14") -> list[DrugCandidate]:
    """Find drugs targeting a protein.

    Args:
        target_name: Target protein or enzyme name (e.g., "thymidylate synthase")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        List of drug candidates with their mechanisms and clinical phases.
    """
    return await _runner.run(
        f"Find approved drugs (Phase 4) that target {target_name}. "
        f"Include compounds like fluorouracil and pemetrexed.",
        cq_id=cq_id,
    )
