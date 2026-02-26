# biosciences-temporal

PydanticAI agents with Temporal.io durable workflow execution for the [Open Biosciences](https://github.com/open-biosciences) platform.

## Migration Status

**Wave 3 (Orchestration): Complete** — migrated from predecessor `lifesciences-temporal` (commits `73c6ebe`, `d7ef863`). Wave 2 ([biosciences-mcp](https://github.com/open-biosciences/biosciences-mcp)) is the upstream prerequisite and is operational.

## Design Principle: PydanticAI First, Temporal Second

Agents are fully testable as standalone units before being wrapped in durable Temporal workflows. This means:

- **Unit-test agents** without Temporal infrastructure — run interactively, debug fast
- **Compose into workflows** when durable execution is needed — retries, crash recovery, audit history
- **Activities are thin wrappers** — all agent logic lives in PydanticAI; activities call agents within a contained task boundary

## What This Repo Contains

Migrated from `lifesciences-temporal` (renamed from `cq14_temporal` to `biosciences_temporal`):

- **PydanticAI standalone agents** — one agent per research phase, each independently testable
- **Temporal workflow definitions** — compose agents into durable, resumable pipelines
- **Temporal activity definitions** — wrap MCP tool calls as retriable, heartbeat-aware units
- **Worker configuration** — retry policies, timeouts, `UnsandboxedWorkflowRunner` for PydanticAI compatibility
- **Docker Compose** — Temporal server (ports 7233 gRPC, 8233 UI) + Neo4j local development environment

### CQ14 Pipeline — 5-Phase Research Workflow

The core workflow answers Competency Question 14 (synthetic lethality and drug target discovery):

| Phase | Agent | Purpose |
|-------|-------|---------|
| 1. Anchor | `agents/resolve.py` | Resolve gene symbols to canonical HGNC identifiers |
| 2. Enrich | `agents/enrich.py` | Gather protein functional context from UniProt |
| 3. Expand | `agents/expand.py` | Discover protein-protein and genetic interactions (STRING, BioGRID) |
| 4. Traverse | `agents/drugs.py`, `agents/trials.py` | Follow drug targets (ChEMBL) and clinical trial relationships |
| 5. Validate | `agents/validate.py` | Cross-source verification of all gathered facts |

### Source Layout

```
src/biosciences_temporal/
├── agents/          # PydanticAI agents (standalone, no Temporal required)
├── temporal/        # Workflow definitions, activities, worker config, client
├── config/          # Retry policies and timeout settings
└── scripts/         # Entry points: run_agent, run_worker, run_workflow
docker-compose.yml   # Temporal server + Neo4j infrastructure
```

## Quick Start

```bash
uv sync

# Standalone — no Temporal infrastructure required
uv run python -m src.biosciences_temporal.scripts.run_agent
uv run python -m src.biosciences_temporal.scripts.run_agent --gene-a BRCA1 --gene-b PARP1

# With Temporal durable execution
docker compose up -d                                              # Start infrastructure
uv run python -m src.biosciences_temporal.scripts.run_worker     # Terminal 1: start worker
uv run python -m src.biosciences_temporal.scripts.run_workflow   # Terminal 2: trigger workflow
```

## Why Temporal

Durable execution provides capabilities that plain async pipelines cannot:

- **Crash survival** — workflow state is persisted; resume from last checkpoint after any failure
- **Automatic retries** — transient API failures are retried without restarting the full pipeline
- **Batch scale** — fan out across many gene pairs without managing concurrency manually
- **Audit history** — full workflow event log for debugging and reproducibility

## Why PydanticAI First

Agents are defined independently of Temporal so they can be:

- **Unit-tested** with standard pytest — no Temporal server needed
- **Run interactively** for rapid iteration during development
- **Debugged** without Temporal overhead or sandbox constraints
- **Reused** in other contexts (notebook, CLI, deepagents) without coupling to Temporal

## Environment Variables

```bash
OPENAI_API_KEY=...    # Required — PydanticAI agents call OpenAI
BIOGRID_API_KEY=...   # Required — BioGRID interaction lookups
NCBI_API_KEY=...      # Optional — raises NCBI rate limits
```

## Known Issues

**MCP + Temporal cancel scope conflict** — `MCPServerStreamableHTTP` causes `RuntimeError: Attempted to exit cancel scope in a different task`. Resolved by using `MCPServerStdio`, which keeps the cancel scope contained within each activity task boundary.

**Temporal sandbox incompatibility** — PydanticAI imports `anyio`/`sniffio`, which are incompatible with Temporal's deterministic sandbox. Uses `UnsandboxedWorkflowRunner()` — safe because all non-deterministic work executes in activities, not workflow code.

## Agent Ownership

Maintained by the **Temporal Engineer** (Agent 7). See [AGENTS.md](https://github.com/open-biosciences/biosciences-program/blob/main/AGENTS.md) for full team definitions.

## Dependencies

| Direction | Repository | Relationship |
|-----------|------------|--------------|
| Upstream | [biosciences-mcp](https://github.com/open-biosciences/biosciences-mcp) | Activities call MCP tools via stdio transport |
| Upstream | [biosciences-architecture](https://github.com/open-biosciences/biosciences-architecture) | ADR-001, ADR-004 workflow compliance |

## Related Repositories

- [biosciences-mcp](https://github.com/open-biosciences/biosciences-mcp) — 12 FastMCP API servers (HGNC, UniProt, ChEMBL, Open Targets, STRING, BioGRID, and more)
- [biosciences-deepagents](https://github.com/open-biosciences/biosciences-deepagents) — LangGraph supervisor + 7 specialist agents
- [biosciences-memory](https://github.com/open-biosciences/biosciences-memory) — Graphiti + Neo4j knowledge graph layer
- [biosciences-program](https://github.com/open-biosciences/biosciences-program) — Migration tracking and cross-repo coordination

## License

MIT
