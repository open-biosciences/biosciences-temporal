# CLAUDE.md — biosciences-temporal

## Purpose

Durable execution workflows for life sciences research using Temporal.io, PydanticAI, and MCP servers. This repo is owned by the **Temporal Engineer** agent.

## Architecture

Follows **PydanticAI First, Temporal Second** design:
1. **Agents** are testable standalone (no Temporal required)
2. **Activities** are thin wrappers that call agents
3. **MCP lifecycle** is fully contained within each activity task (one-shot pattern)

### Directory Layout (post-migration)

```
biosciences-temporal/
├── src/
│   ├── agents/              # PydanticAI agents (standalone)
│   │   ├── models.py        # Shared Pydantic models
│   │   ├── base.py          # MCP client factory
│   │   ├── resolve.py       # Gene resolution agent
│   │   ├── enrich.py        # Protein enrichment agent
│   │   ├── expand.py        # Interaction network agent
│   │   ├── drugs.py         # Drug discovery agent
│   │   ├── trials.py        # Clinical trials agent
│   │   ├── validate.py      # Validation agents
│   │   └── cq14.py          # Orchestrated workflow
│   │
│   ├── temporal/            # Temporal-specific code
│   │   ├── activities.py    # Thin wrappers around agents
│   │   ├── workflows.py     # Workflow definitions
│   │   ├── worker.py        # Worker configuration
│   │   └── client.py        # Workflow trigger/resume
│   │
│   ├── config/              # Timeouts, retry policies
│   └── scripts/             # Entry points
├── docker-compose.yml       # Temporal + Neo4j infrastructure
└── TESTING_PLAN.md
```

### CQ14 Workflow Phases

1. **Anchor** — Resolve gene symbols to canonical HGNC identifiers
2. **Enrich** — Get protein functional context from UniProt
3. **Expand** — Find protein-protein and genetic interactions (STRING, BioGRID)
4. **Traverse** — Search for drugs (ChEMBL) and clinical trials
5. **Validate** — Cross-check all claims against source databases

## Development Commands

```bash
uv sync                          # Install dependencies

# Standalone (no Temporal required)
uv run python -m src.scripts.run_agent
uv run python -m src.scripts.run_agent --gene-a BRCA1 --gene-b PARP1

# With Temporal
uv run python -m src.scripts.run_worker     # Start worker
uv run python -m src.scripts.run_workflow   # Trigger workflow
uv run python -m src.scripts.run_workflow -w <workflow-id>  # Resume
```

## Environment Variables

```bash
OPENAI_API_KEY=...         # For PydanticAI agents
BIOGRID_API_KEY=...        # For BioGRID interactions
NCBI_API_KEY=...           # For higher NCBI rate limits (optional)
```

## Known Issues

### MCP + Temporal Cancel Scope Conflict
The original `MCPServerStreamableHTTP` transport causes `RuntimeError: Attempted to exit cancel scope in a different task`. **Resolution**: Using `MCPServerStdio` which keeps cancel scope contained within each activity task.

### Temporal Sandbox
PydanticAI imports `anyio/sniffio` which are incompatible with Temporal's deterministic sandbox. Uses `UnsandboxedWorkflowRunner()` — safe because all non-deterministic work happens in activities.

## Dependencies

- **Upstream**: `biosciences-mcp` (MCP servers via stdio transport), `biosciences-architecture` (workflow compliance)
- **Sibling**: `biosciences-deepagents` (shares agent patterns)
- **Infrastructure**: Temporal.io (ports 7233 gRPC, 8233 UI)

## Conventions

- Python >=3.11, uv, hatchling, ruff, pyright
- Pydantic v2 for all models
- PydanticAI for agent definitions
- pytest with marker-based test organization

## Pre-Migration Source

Until Wave 3 migration: `/home/donbr/graphiti-org/lifesciences-temporal/`
