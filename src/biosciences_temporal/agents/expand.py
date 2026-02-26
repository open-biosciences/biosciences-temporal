"""
Interaction expansion agent - Phase 3: Expand.

Finds protein-protein and genetic interactions using STRING and BioGRID.
"""

from .base import AgentMetadata, AgentRunner
from .models import GeneInteraction

INSTRUCTIONS = """
You find protein-protein and genetic interactions.

WORKFLOW:
1. Use string_search_proteins(query="GENE_SYMBOL") to get STRING ID
2. Use string_get_interactions(string_id="9606.ENSPXXXX") for physical interactions
3. Use biogrid_get_interactions(gene_symbol="GENE") for genetic interactions

IMPORTANT: For synthetic lethality, look for "Negative Genetic" interactions
in BioGRID results. These indicate synthetic lethal relationships.

Return interactions with their type, score, and evidence source.
"""

_runner = AgentRunner(
    output_type=list[GeneInteraction],
    instructions=INSTRUCTIONS,
    name="expand_interactions",
    metadata=AgentMetadata(
        phase="expand",
        action="interactions",
        entity_type="interaction",
        source="STRING,BioGRID",
    ),
)


async def expand_interactions(gene_symbol: str, cq_id: str = "cq14") -> list[GeneInteraction]:
    """Find protein-protein and genetic interactions for a gene.

    Args:
        gene_symbol: Gene symbol to query (e.g., "TYMS")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        List of interactions from STRING and BioGRID.
    """
    return await _runner.run(
        f"Find protein-protein and genetic interactions for gene {gene_symbol}. "
        f"Look for physical interactions in STRING and genetic interactions in BioGRID.",
        cq_id=cq_id,
    )
