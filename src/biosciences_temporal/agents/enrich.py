"""
Protein enrichment agent - Phase 2: Enrich.

Gets protein functional context from UniProt.
"""

from .base import AgentMetadata, AgentRunner
from .models import ProteinFunction

INSTRUCTIONS = """
You get protein functional context from UniProt.

WORKFLOW:
1. Use uniprot_get_protein(uniprot_id="UniProtKB:XXXXX") with the UniProt accession

IMPORTANT: Extract the protein function summary and key biological keywords.
"""

_runner = AgentRunner(
    output_type=ProteinFunction,
    instructions=INSTRUCTIONS,
    name="enrich_protein",
    metadata=AgentMetadata(
        phase="enrich",
        action="protein",
        entity_type="protein",
        source="UniProt",
    ),
)


async def enrich_protein(uniprot_id: str, cq_id: str = "cq14") -> ProteinFunction:
    """Get protein functional context.

    Args:
        uniprot_id: UniProt accession (e.g., "UniProtKB:P04637" or just "P04637")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        ProteinFunction with function summary and keywords.
    """
    # Ensure CURIE format
    if not uniprot_id.startswith("UniProtKB:"):
        uniprot_id = f"UniProtKB:{uniprot_id}"

    return await _runner.run(f"Get protein function for {uniprot_id}", cq_id=cq_id)
