# CQ14 Temporal Project Refactoring Plan

**Date**: 2026-01-19
**Goal**: Reorganize cq14_temporal into a standard, maintainable structure

## Current Issues

1. **Flat structure** - All files in one directory
2. **Non-standard naming** - `*_oneshot.py` suffix confuses the purpose
3. **Test files mixed with source** - `test_agents_standalone.py` in main folder
4. **Unclear separation** - PydanticAI agents vs Temporal wrappers not distinct

## Proposed Structure

Based on Temporal Python SDK samples and PydanticAI documentation:

```
src/cq14_temporal/
├── __init__.py
├── README.md
│
├── agents/                      # PydanticAI agents (can run standalone)
│   ├── __init__.py
│   ├── models.py                # Shared Pydantic models
│   ├── resolve.py               # Gene resolution agent
│   ├── enrich.py                # Protein enrichment agent
│   ├── expand.py                # Interaction network agent
│   ├── traverse.py              # Drug/trial discovery agent
│   ├── validate.py              # Validation agent
│   └── cq14.py                  # Orchestrated CQ14 flow (no Temporal)
│
├── temporal/                    # Temporal-specific code
│   ├── __init__.py
│   ├── activities.py            # Activity definitions (wrap agents)
│   ├── workflows.py             # Workflow definitions
│   ├── worker.py                # Worker configuration
│   └── client.py                # Workflow trigger/resume
│
├── config/                      # Configuration
│   ├── __init__.py
│   ├── timeouts.py              # Activity timeouts
│   └── retry_policies.py        # Retry configuration
│
├── scripts/                     # Entry points and utilities
│   ├── run_agent.py             # Run PydanticAI agent standalone
│   ├── run_workflow.py          # Trigger Temporal workflow
│   └── run_worker.py            # Start Temporal worker
│
└── deprecated/                  # Preserved for reference
    ├── README.md
    ├── agents.py
    ├── workflow.py
    ├── worker.py
    └── run_workflow.py
```

## Design Principles

### 1. PydanticAI First, Temporal Second

From [PydanticAI Durable Execution docs](https://ai.pydantic.dev/durable_execution/temporal/index.md):
- Agents should be testable without Temporal
- Temporal activities should be thin wrappers around agent logic
- Non-deterministic work (LLM calls, API calls) belongs in activities

**Workflow** (agents/cq14.py):
```python
class CQ14Agent:
    """Standalone PydanticAI orchestration - no Temporal required."""

    async def run(self, gene_a: str, gene_b: str) -> CQ14Result:
        # Phase 1: Anchor
        gene_a_resolved = await self.resolve_gene(gene_a)
        gene_b_resolved = await self.resolve_gene(gene_b)
        # ... etc
```

**Activity** (temporal/activities.py):
```python
@activity.defn
async def resolve_gene(gene_symbol: str) -> dict:
    """Temporal activity wrapping the resolve agent."""
    agent = ResolveAgent()
    result = await agent.run(gene_symbol)
    return result.model_dump()
```

### 2. Standard Temporal Patterns

From [Temporal Python SDK docs](https://docs.temporal.io/develop/python/core-application):
- Workflows orchestrate activities
- Activities perform non-deterministic work
- Workers poll task queues and execute both

```python
# temporal/worker.py
async def main():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue="cq14-task-queue",
        workflows=[CQ14Workflow],
        activities=[resolve_gene, enrich_protein, expand_interactions, ...],
    )
    await worker.run()
```

### 3. MCP Lifecycle Management

Due to [python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577), MCP connections must be fully contained within activity task boundaries:

```python
@activity.defn
async def resolve_gene(gene_symbol: str) -> dict:
    # MCP lifecycle fully contained in activity
    mcp = MCPServerStdio(...)
    async with mcp:
        agent = Agent(..., toolsets=[mcp])
        result = await agent.run(gene_symbol)
    return result.model_dump()
```

## Migration Steps

### Phase 1: Create Directory Structure ✓
- [x] Create `agents/`, `temporal/`, `config/`, `scripts/` folders
- [x] Move deprecated files (already done)

### Phase 2: Extract Agents ✓
- [x] Create `agents/models.py` with shared Pydantic models
- [x] Extract agent logic to `agents/*.py` (resolve, enrich, expand, drugs, trials, validate)
- [x] Create `agents/cq14.py` standalone orchestrator

### Phase 3: Refactor Temporal Layer ✓
- [x] Create thin activity wrappers in `temporal/activities.py`
- [x] Create workflow in `temporal/workflows.py`
- [x] Create worker in `temporal/worker.py`
- [x] Create `temporal/client.py` for triggering workflows

### Phase 4: Update Scripts ✓
- [x] `scripts/run_agent.py` - Run standalone (no Temporal)
- [x] `scripts/run_workflow.py` - Trigger via Temporal
- [x] `scripts/run_worker.py` - Start worker

### Phase 5: Testing ✓
- [x] Validate imports work correctly
- [x] Validate agents work standalone (run `scripts/run_agent.py`)
- [x] Validate activities work with Temporal (run worker + workflow)
- [x] Validate full workflow end-to-end
- [x] Clean up legacy files after validation (removed `*_oneshot.py` files)

## File Mapping

| Current | Proposed |
|---------|----------|
| `cq14_agent.py` | `agents/cq14.py` |
| `activities_oneshot.py` | `temporal/activities.py` + `agents/*.py` |
| `workflow_oneshot.py` | `temporal/workflows.py` |
| `worker_oneshot.py` | `temporal/worker.py` |
| `run_oneshot.py` | `scripts/run_workflow.py` |
| `config.py` | `config/timeouts.py` |
| `retry_policies.py` | `config/retry_policies.py` |
| `test_agents_standalone.py` | `scripts/run_agent.py` or `tests/` |

## References

### PydanticAI Documentation
- [Durable Execution Overview](https://ai.pydantic.dev/durable_execution/index.md)
- [Temporal Integration](https://ai.pydantic.dev/durable_execution/temporal/index.md)
- [Multi-agent Applications](https://ai.pydantic.dev/multi-agent/index.md)
- [MCP Client](https://ai.pydantic.dev/mcp/client/index.md)

### Temporal Documentation
- [Python SDK Core Application](https://docs.temporal.io/develop/python/core-application)
- [Workflow Definition](https://docs.temporal.io/workflow-definition)
- [Activity Definition](https://docs.temporal.io/activities)
- [Python SDK Samples](https://github.com/temporalio/samples-python)

### Known Issues
- [MCP python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577) - Cancel scope lifecycle
- [pydantic-ai #2818](https://github.com/pydantic/pydantic-ai/issues/2818) - Parallel MCP servers

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Agents in separate folder | Testable without Temporal |
| Thin activity wrappers | Separation of concerns |
| Config in own folder | Centralized configuration |
| Scripts folder | Clear entry points |
| Keep deprecated | Reference until MCP fix |
