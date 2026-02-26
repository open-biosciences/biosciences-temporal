# Agent Metadata Specification

This document defines the valid values for agent metadata fields used in Logfire tracing.

## Overview

Each agent reports structured metadata via the `AgentMetadata` dataclass, enabling:
- Filtering traces by workflow phase
- Analyzing performance by data source
- Tracking entity types through the pipeline

## Fields

### `phase`

The workflow phase this agent belongs to.

| Value | Description |
|-------|-------------|
| `anchor` | Phase 1: Resolve fuzzy identifiers to canonical IDs |
| `enrich` | Phase 2: Add functional context to entities |
| `expand` | Phase 3: Discover related entities and interactions |
| `traverse` | Phase 4: Find drugs and clinical trials |
| `validate` | Phase 5: Cross-check claims against source databases |

### `action`

The specific action being performed within the phase.

| Value | Phase | Description |
|-------|-------|-------------|
| `resolve` | anchor | Resolve gene symbols to HGNC IDs |
| `protein` | enrich | Get protein function from UniProt |
| `interactions` | expand | Find protein-protein and genetic interactions |
| `drugs` | traverse | Search for drug candidates |
| `trials` | traverse | Search for clinical trials |
| `gene` | validate | Validate gene identifiers |
| `drug` | validate | Validate compound existence |
| `trial` | validate | Validate trial existence |
| `sl` | validate | Validate synthetic lethality evidence |

### `entity_type`

The type of biological entity being processed.

| Value | Description |
|-------|-------------|
| `gene` | Gene (symbol, HGNC ID, Entrez ID) |
| `protein` | Protein (UniProt accession) |
| `interaction` | Gene-gene or protein-protein interaction |
| `compound` | Chemical compound or drug (ChEMBL ID) |
| `trial` | Clinical trial (NCT ID) |
| `gene_pair` | Pair of genes for synthetic lethality analysis |

### `source`

The primary data source being queried.

| Value | URL | Description |
|-------|-----|-------------|
| `HGNC` | https://www.genenames.org/ | HUGO Gene Nomenclature Committee |
| `UniProt` | https://www.uniprot.org/ | Universal Protein Resource |
| `STRING` | https://string-db.org/ | Protein-protein interaction networks |
| `BioGRID` | https://thebiogrid.org/ | Biological interaction repository |
| `ChEMBL` | https://www.ebi.ac.uk/chembl/ | Bioactive molecule database |
| `ClinicalTrials.gov` | https://clinicaltrials.gov/ | Clinical trial registry |

Note: Multiple sources can be specified as comma-separated values (e.g., `STRING,BioGRID`).

### `cq_id`

Competency question identifier for attribution. Default: `cq14`

This field links traces to the research question being addressed.

## Example Usage

```python
from src.cq14_temporal.agents.base import AgentMetadata, AgentRunner
from src.cq14_temporal.agents.models import GeneInfo

runner = AgentRunner(
    output_type=GeneInfo,
    instructions="Resolve gene symbols...",
    name="anchor_resolve",
    metadata=AgentMetadata(
        phase="anchor",
        action="resolve",
        entity_type="gene",
        source="HGNC",
    ),
)

result = await runner.run("Resolve gene: TP53", cq_id="cq14")
```

## Logfire Queries

Filter traces by metadata:

```python
# Find all anchor phase traces
logfire.find_traces({"metadata.phase": "anchor"})

# Find all BioGRID queries
logfire.find_traces({"metadata.source": {"$regex": "BioGRID"}})

# Find validation failures
logfire.find_traces({
    "metadata.phase": "validate",
    "output.verified": False
})
```
