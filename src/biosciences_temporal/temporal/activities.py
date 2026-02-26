"""
Temporal activity definitions for CQ14 workflow.

These are thin wrappers around the PydanticAI agents defined in agents/.
Each activity creates its own MCP client, uses it, and closes it within
the same task context (one-shot pattern) to avoid cancel scope conflicts.
"""

from temporalio import activity

# Import agents (these are standalone PydanticAI agents)
from ..agents.resolve import resolve_gene as _resolve_gene
from ..agents.enrich import enrich_protein as _enrich_protein
from ..agents.expand import expand_interactions as _expand_interactions
from ..agents.drugs import find_drugs as _find_drugs
from ..agents.trials import search_trials as _search_trials
from ..agents.validate import (
    validate_gene as _validate_gene,
    validate_drug as _validate_drug,
    validate_trial as _validate_trial,
    validate_synthetic_lethality as _validate_synthetic_lethality,
)


# --- Phase 1: Anchor ---

@activity.defn
async def resolve_gene(gene_symbol: str) -> dict:
    """Resolve a gene symbol to canonical identifiers.

    Temporal activity wrapping the resolve agent.
    """
    result = await _resolve_gene(gene_symbol)
    return result.model_dump()


# --- Phase 2: Enrich ---

@activity.defn
async def enrich_protein(uniprot_id: str) -> dict:
    """Get protein functional context.

    Temporal activity wrapping the enrich agent.
    """
    result = await _enrich_protein(uniprot_id)
    return result.model_dump()


# --- Phase 3: Expand ---

@activity.defn
async def expand_interactions(gene_symbol: str) -> dict:
    """Get protein-protein and genetic interactions.

    Temporal activity wrapping the expand agent.
    """
    result = await _expand_interactions(gene_symbol)
    return {"interactions": [i.model_dump() for i in result]}


# --- Phase 4: Traverse ---

@activity.defn
async def find_drugs(target_name: str) -> list[dict]:
    """Find drugs targeting a protein.

    Temporal activity wrapping the drugs agent.
    """
    result = await _find_drugs(target_name)
    return [d.model_dump() for d in result]


@activity.defn
async def search_trials(drug_name: str, condition: str = "cancer") -> list[dict]:
    """Search clinical trials for a drug.

    Temporal activity wrapping the trials agent.
    """
    result = await _search_trials(drug_name, condition)
    return [t.model_dump() for t in result]


# --- Phase 5: Validate ---

@activity.defn
async def validate_gene(claim: str) -> dict:
    """Validate gene identifiers.

    Temporal activity wrapping the gene validation agent.
    """
    result = await _validate_gene(claim)
    return result.model_dump()


@activity.defn
async def validate_mechanism(claim: str) -> dict:
    """Validate drug/compound exists in ChEMBL.

    Temporal activity wrapping the drug validation agent.
    """
    result = await _validate_drug(claim)
    return result.model_dump()


@activity.defn
async def validate_trial(nct_id: str) -> dict:
    """Validate clinical trial exists.

    Temporal activity wrapping the trial validation agent.
    """
    result = await _validate_trial(nct_id)
    return result.model_dump()


@activity.defn
async def validate_synthetic_lethality(gene_a: str, gene_b: str) -> dict:
    """Validate synthetic lethality claim.

    Temporal activity wrapping the synthetic lethality validation agent.
    """
    result = await _validate_synthetic_lethality(gene_a, gene_b)
    return result.model_dump()


# --- Activity Registry ---

ALL_ACTIVITIES = [
    resolve_gene,
    enrich_protein,
    expand_interactions,
    find_drugs,
    search_trials,
    validate_gene,
    validate_mechanism,
    validate_trial,
    validate_synthetic_lethality,
]
