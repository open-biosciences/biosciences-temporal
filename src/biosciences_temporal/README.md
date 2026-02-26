# CQ14 Temporal Workflow

Durable execution of the Fuzzy-to-Fact protocol for validating synthetic lethality claims using Temporal.io.

## Overview

This module implements CQ14 (Synthetic Lethality Validation) as a Temporal.io workflow with:
- **5 phases** of the Fuzzy-to-Fact protocol
- **9 activities** with contained MCP lifecycles
- **stdio transport** to avoid async cancel scope conflicts
- **Full execution history** for debugging and resumption

## Package Structure

```
biosciences_temporal/
├── agents/              # PydanticAI agents (can run standalone)
│   ├── models.py        # Shared Pydantic models
│   ├── base.py          # MCP client factory
│   ├── resolve.py       # Gene resolution agent
│   ├── enrich.py        # Protein enrichment agent
│   ├── expand.py        # Interaction network agent
│   ├── drugs.py         # Drug discovery agent
│   ├── trials.py        # Clinical trials agent
│   ├── validate.py      # Validation agents
│   └── cq14.py          # Orchestrated workflow
│
├── temporal/            # Temporal-specific code
│   ├── activities.py    # Thin wrappers around agents
│   ├── workflows.py     # Workflow definitions
│   ├── worker.py        # Worker configuration
│   └── client.py        # Workflow trigger/resume
│
├── config/              # Configuration
│   ├── timeouts.py      # Activity timeouts
│   └── retry_policies.py # Retry configuration
│
├── scripts/             # Entry points
│   ├── run_agent.py     # Run standalone (no Temporal)
│   ├── run_worker.py    # Start Temporal worker
│   └── run_workflow.py  # Trigger Temporal workflow
│
└── deprecated/          # Preserved for reference (MCP cancel scope bug)
```

## Key Design Principles

### 1. PydanticAI First, Temporal Second

Agents in `agents/` are testable without Temporal. The Temporal layer (`temporal/`) provides thin wrappers for durable execution.

### 2. One-Shot Activity Pattern

Each activity creates its own MCP client, uses it, and closes it within the same task context:

```python
# agents/resolve.py - Standalone agent
async def resolve_gene(gene_symbol: str) -> GeneInfo:
    mcp = create_mcp_client()
    async with mcp:
        agent = Agent(MODEL, instructions=..., output_type=GeneInfo, toolsets=[mcp])
        result = await agent.run(f"Resolve gene: {gene_symbol}")
    return result.output

# temporal/activities.py - Thin wrapper
@activity.defn
async def resolve_gene(gene_symbol: str) -> dict:
    result = await _resolve_gene(gene_symbol)
    return result.model_dump()
```

### 3. Separation of Concerns

| Layer | Location | Purpose |
|-------|----------|---------|
| Models | `agents/models.py` | Shared Pydantic models |
| Logic | `agents/*.py` | Agent logic (standalone) |
| Temporal | `temporal/activities.py` | Thin wrappers |
| Config | `config/*.py` | Timeouts, retries |

## Quick Start

### 1. Prerequisites

```bash
# Temporal server running
docker-compose up -d

# Environment variables
export OPENAI_API_KEY="sk-..."
export BIOGRID_API_KEY="..."  # Free: https://webservice.thebiogrid.org/
```

### 2. Run Standalone (No Temporal)

```bash
# Default (TP53-TYMS)
uv run python -m src.biosciences_temporal.scripts.run_agent

# Custom genes
uv run python -m src.biosciences_temporal.scripts.run_agent --gene-a BRCA1 --gene-b PARP1
```

### 3. Run with Temporal (Durable Execution)

```bash
# Terminal 1: Start worker
uv run python -m src.biosciences_temporal.scripts.run_worker

# Terminal 2: Trigger workflow
uv run python -m src.biosciences_temporal.scripts.run_workflow

# Custom genes
uv run python -m src.biosciences_temporal.scripts.run_workflow --gene-a BRCA1 --gene-b PARP1

# Resume existing workflow
uv run python -m src.biosciences_temporal.scripts.run_workflow -w <workflow-id>
```

## Workflow Phases

```
Phase 1: Anchor      - Resolve gene symbols to canonical IDs (parallel)
Phase 2: Enrich      - Get protein functional context (parallel)
Phase 3: Expand      - Build interaction networks
Phase 4a: Traverse   - Find drugs targeting the protein
Phase 4b: Traverse   - Search trials using discovered drug names
Phase 5: Validate    - Cross-check all claims (parallel)
```

**Note**: Phases 4a and 4b run sequentially so drug names from 4a can inform the trial search in 4b.

## Activity Configuration

| Type | Timeout | Retry | Used For |
|------|---------|-------|----------|
| SHORT | 3 min | 3 attempts | resolve_gene, enrich_protein, validators |
| LONG | 5 min | 5 attempts | expand_interactions, find_drugs, search_trials |

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes | Pydantic AI agent LLM calls |
| `BIOGRID_API_KEY` | Yes | BioGRID interactions API |
| `NCBI_API_KEY` | No | Higher NCBI/Entrez rate limits |

## Deprecated Files

Moved to `deprecated/` folder. These files use the original TemporalAgent pattern which is valid code but currently incompatible with MCP due to a cancel scope lifecycle bug.

See `deprecated/README.md` for details.

**Tracking Issue**: [python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577)

## Known Issues

### Cancel Scope Bug (Resolved)

The MCP Python SDK has a bug where cancel scopes exit in different tasks than entered. This happens when MCP connections opened in one Temporal activity task are closed in another.

**Solution**: Use `MCPServerStdio` with environment inheritance to spawn isolated MCP processes per activity.

**Tracking**: [python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577)

### Temporal Sandbox Compatibility (Resolved)

PydanticAI imports `anyio/sniffio` which are incompatible with Temporal's deterministic sandbox.

**Solution**: The worker uses `UnsandboxedWorkflowRunner()` to disable sandbox restrictions. This is safe because all non-deterministic work happens in activities.

See [Temporal Python SDK Sandbox docs](https://docs.temporal.io/develop/python/temporal-sdk-sandbox) for details.

### Clinical Trials Empty Results (Fixed)

The trials phase was returning empty because the workflow used "TYMS inhibitor" (a mechanism) instead of actual drug names like "pemetrexed" or "fluorouracil".

**Fix**: Phase 4 now sequences drug discovery before trial search:
1. Phase 4a finds drugs targeting the protein
2. Phase 4b uses discovered drug names for trial search

## Official Documentation

- [PydanticAI Durable Execution](https://ai.pydantic.dev/durable_execution/temporal/) - TemporalAgent pattern
- [Temporal Python SDK](https://github.com/temporalio/sdk-python) - Worker and sandbox configuration
- [Temporal Python SDK Samples](https://github.com/temporalio/samples-python) - Example patterns
