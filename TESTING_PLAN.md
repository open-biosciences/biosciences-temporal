# Testing Plan: Stdio Transport for Temporal + MCP Integration

**Created**: January 15, 2026
**Purpose**: Validate that stdio transport resolves the cancel scope conflicts between Temporal and MCP.

## Background

The original implementation used `MCPServerStreamableHTTP` to connect to the FastMCP Cloud endpoint. This caused `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in` due to anyio's requirement that cancel scopes exit in the same task they were entered.

Temporal activities run in separate tasks, and MCP connections opened in one task were being closed in another, violating this requirement.

## Hypothesis

Using `MCPServerStdio` instead of `MCPServerStreamableHTTP` should resolve the issue because:

1. **Process isolation**: Each activity spawns a fresh subprocess for the MCP server
2. **Cancel scope containment**: The async context manager (`async with mcp:`) fully opens and closes within the same Temporal task
3. **No cross-task state**: Stdio transport has no persistent connection state that crosses task boundaries

## Test Steps

### Prerequisites

1. **Temporal server running** (ports 7233 for gRPC, 8233 for UI):
   ```bash
   # Already running per user confirmation
   # Check: curl http://localhost:8233
   ```

2. **Environment variables set**:
   ```bash
   export OPENAI_API_KEY=...    # Required for Pydantic AI agents
   export BIOGRID_API_KEY=...   # Required for BioGRID interactions
   export NCBI_API_KEY=...      # Optional, for higher rate limits
   ```

### Step 1: Start the Worker

```bash
uv run python -m src.biosciences_temporal.worker_oneshot
```

Expected output:
```
Worker started, listening on task queue: cq14-oneshot-task-queue
```

### Step 2: Run the Workflow

In a separate terminal:

```bash
uv run python -m src.biosciences_temporal.run_oneshot
```

Expected behavior:
- Workflow starts and logs phases 1-5
- Each activity spawns a subprocess running the gateway MCP server
- **NO** `cancel scope` errors should appear
- Workflow completes with results

### Step 3: Verify in Temporal UI

Open http://localhost:8233 and:
1. Find the workflow execution (ID starts with `cq14-oneshot-`)
2. Check that all activities completed successfully
3. No activity failures due to cancel scope errors

## Success Criteria

- [ ] Worker starts without errors
- [ ] Workflow executes Phase 1 (gene resolution) without cancel scope errors
- [ ] All 5 phases complete successfully
- [ ] Results returned with gene resolutions, protein contexts, interactions, drugs, and validations

## Failure Scenarios

### If cancel scope errors still occur:

1. Check if the error is in the same location (`mcp/client/streamable_http.py`)
   - If yes: stdio should fix it, investigate further
   - If no: different issue, check the stack trace

2. Try running a single activity in isolation:
   ```python
   # test_single_activity.py
   import asyncio
   from src.biosciences_temporal.activities_oneshot import resolve_gene

   async def main():
       result = await resolve_gene("TP53")
       print(result)

   asyncio.run(main())
   ```

### If subprocess spawn fails:

1. Verify the gateway server can run standalone:
   ```bash
   # From the biosciences-mcp sibling directory
   uv run fastmcp run src/biosciences_mcp/servers/gateway.py
   ```

2. Check the `BIOSCIENCES_MCP_PATH` environment variable resolves correctly

## Lessons Learned

### 1. Transport Choice Matters for Execution Model

The MCP transport (stdio vs HTTP/SSE) has significant implications for async execution:

| Transport | Pros | Cons |
|-----------|------|------|
| **stdio** | Process isolation, no cross-task state | Subprocess overhead per request |
| **Streamable HTTP** | Persistent connections, efficient | Cancel scope conflicts with Temporal |
| **SSE** | Real-time streaming | Same async context issues |

**Takeaway**: stdio is the safest choice for durable execution frameworks like Temporal that run activities in separate tasks.

### 2. One-Shot Pattern is Pragmatic

The "one-shot" pattern (create client → use → close within single activity) works regardless of transport. It's more verbose but avoids lifecycle management complexity.

### 3. Upstream Bug is Known

- [pydantic-ai #2818](https://github.com/pydantic/pydantic-ai/issues/2818) - Parallel MCP servers (milestone: 2026-01)
- [python-sdk #521](https://github.com/modelcontextprotocol/python-sdk/issues/521) - SSE cancel scope fix (merged Dec 2025)
- [python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577) - Multiple MCPClient cleanup order

Monitor these for upstream fixes that may enable `MCPServerStreamableHTTP` with Temporal in the future.

### 4. Client Layer May Be Better Fit

For simple use cases, directly using the `lifesciences_mcp.clients` layer (e.g., `HGNCClient`, `UniProtClient`) with Temporal activities may be simpler than the full MCP server approach. The clients are pure async httpx calls with no MCP lifecycle management.

### 5. Temporal vs Direct Async

Consider whether Temporal's durability benefits outweigh the integration complexity:

| Use Case | Recommended Approach |
|----------|---------------------|
| Long-running workflows (>10 min) | Temporal with stdio MCP |
| Workflow resumption needed | Temporal with stdio MCP |
| Simple agent tasks (<2 min) | Direct async with clients |
| Batch processing | Direct async with clients |

## Next Steps After Successful Test

1. **Document the stdio pattern** in the project README
2. **Update TEMPORAL_MCP_STATUS.md** with results
3. **Consider** whether to add an environment variable toggle for transport type
4. **Monitor** upstream issues for fixes that could enable HTTP transport

## Commands Reference

```bash
# Start worker
uv run python -m src.biosciences_temporal.worker_oneshot

# Run workflow with defaults
uv run python -m src.biosciences_temporal.run_oneshot

# Run with custom genes
uv run python -m src.biosciences_temporal.run_oneshot --gene-a BRCA1 --gene-b PARP1

# Resume existing workflow
uv run python -m src.biosciences_temporal.run_oneshot -w <workflow-id>
```
