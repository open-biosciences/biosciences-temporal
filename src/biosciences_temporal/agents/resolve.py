"""
Gene resolution agent - Phase 1: Anchor.

Resolves gene symbols to canonical HGNC identifiers with cross-references.
"""

from .base import AgentMetadata, AgentRunner
from .models import GeneInfo

INSTRUCTIONS = """
You resolve gene symbols to canonical HGNC identifiers.

WORKFLOW:
1. Use hgnc_search_genes(query="GENE_SYMBOL") to find candidates
2. Use hgnc_get_gene(hgnc_id="HGNC:NNNNN") to get full details

IMPORTANT: Return the canonical HGNC CURIE format (e.g., "HGNC:11998")
and cross-references to UniProt, Entrez, and Ensembl.
"""

_runner = AgentRunner(
    output_type=GeneInfo,
    instructions=INSTRUCTIONS,
    name="anchor_resolve",
    metadata=AgentMetadata(
        phase="anchor",
        action="resolve",
        entity_type="gene",
        source="HGNC",
    ),
)


async def resolve_gene(gene_symbol: str, cq_id: str = "cq14") -> GeneInfo:
    """Resolve a gene symbol to canonical HGNC identifiers.

    Args:
        gene_symbol: Gene symbol to resolve (e.g., "TP53", "TYMS")
        cq_id: Competency question identifier for Logfire attribution

    Returns:
        GeneInfo with HGNC ID and cross-references.
    """
    return await _runner.run(f"Resolve gene: {gene_symbol}", cq_id=cq_id)
