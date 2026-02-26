# CQ14 Temporal + MCP Integration Status

**Last Updated**: January 14, 2026
**Pydantic AI Version**: 1.42.0
**MCP SDK Version**: 1.25.0

## Summary

The CQ14 workflow using Pydantic AI TemporalAgent with MCP servers hits a known bug in the MCP Python SDK related to anyio cancel scope management. **The one-shot pattern is the recommended workaround** and is now production-ready with retry policies and CLI argument parsing.

## What Works

| Component | Status |
|-----------|--------|
| **One-shot activities with MCP** | ✅ All 9 agents pass |
| Standalone Pydantic AI agents with MCP | ✅ All 9 agents pass |
| MCP → OpenAI → Pydantic output parsing | ✅ Works correctly |
| Temporal workflows (without MCP) | ✅ Works per documentation |
| **CLI with argument parsing** | ✅ Implemented |
| **Retry policies (ADR-001)** | ✅ Implemented |
| **Workflow resumption** | ✅ Implemented |

## Working Solution: One-Shot Pattern

The one-shot pattern contains the MCP lifecycle within each activity, avoiding the cancel scope bug.

### Architecture

```
src/cq14_temporal/
├── retry_policies.py    # Retry policies (SHORT/LONG)
├── config.py            # Activity configs with timeouts and retry policies
├── activities_oneshot.py # 9 activities with contained MCP lifecycles
├── workflow_oneshot.py  # 5-phase orchestration
├── worker_oneshot.py    # Worker registration
└── run_oneshot.py       # CLI with argument parsing
```

### Usage

```bash
# Start worker
python -m src.cq14_temporal.worker_oneshot

# Run with defaults (TP53-TYMS)
python -m src.cq14_temporal.run_oneshot

# Run with custom genes
python -m src.cq14_temporal.run_oneshot --gene-a BRCA1 --gene-b PARP1

# Resume existing workflow
python -m src.cq14_temporal.run_oneshot -w cq14-oneshot-TP53-TYMS-abc12345
```

### Retry Policies

Retry policies are based on ADR-001 error codes:

```python
# Non-retryable errors (retrying won't help)
NON_RETRYABLE_ERRORS = [
    "UNRESOLVED_ENTITY",   # Raw string passed to strict tool
    "AMBIGUOUS_QUERY",     # Query too short
    "ENTITY_NOT_FOUND",    # Valid CURIE but no record
    "ValidationError",     # Pydantic validation
]

# Short activities: 3 attempts, 2s→1min backoff
SHORT_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
    non_retryable_error_types=NON_RETRYABLE_ERRORS,
)

# Long activities: 5 attempts, 5s→3min backoff
LONG_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=3),
    maximum_attempts=5,
    non_retryable_error_types=NON_RETRYABLE_ERRORS,
)
```

## What Fails

**Error**: `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in`

**Location**: `mcp/client/streamable_http.py` line 461

**Cause**: Temporal activities run in separate tasks. MCP connections are opened in one activity task but closed in another, violating anyio's requirement that cancel scopes exit in the same task they were entered.

## Grounded Evidence

### GitHub Issues (Active)

1. **[pydantic/pydantic-ai #2818](https://github.com/pydantic/pydantic-ai/issues/2818)** - Parallel MCP servers
   - Status: **OPEN** (Milestone: 2026-01)
   - Assignee: DouweM
   - Root cause: Multiple MCP server instances in concurrent contexts

2. **[modelcontextprotocol/python-sdk #521](https://github.com/modelcontextprotocol/python-sdk/issues/521)** - SSE client cancel scope
   - Status: **CLOSED** (Fixed December 2, 2025)
   - Fix: Shield cleanup operations with `anyio.CancelScope(shield=True)`
   - Note: Fix is for SSE transport, may not cover Streamable HTTP

3. **[modelcontextprotocol/python-sdk #577](https://github.com/modelcontextprotocol/python-sdk/issues/577)** - Multiple MCPClient instances
   - Status: OPEN
   - Issue: Non-FILO cleanup order causes cascade of errors

### Pydantic AI Documentation

From [Durable Execution with Temporal](https://ai.pydantic.dev/durable_execution/temporal/):

> "Durable agents have full support for streaming and MCP, with the added benefit of fault tolerance."

> "MCP server communication all need to be offloaded to Temporal activities"

> "their names are derived from the agent's `name` and the toolsets' `id`s. These fields are normally optional, but are **required to be set when using Temporal.**"

**Note**: No complete MCP + Temporal example exists in the documentation as of this date.

## Current Configuration

Our agents.py correctly sets both required fields:

```python
anchor_mcp = MCPServerStreamableHTTP(
    url=LIFESCIENCES_MCP_URL,
    id='lifesciences_mcp',  # Required for Temporal
    timeout=120.0,
)

anchor_agent = Agent(
    'openai:gpt-4.1-mini',
    ...,
    toolsets=[anchor_mcp],
    name='anchor_agent',  # Required for Temporal
)
```

## Workarounds to Try

### Option 1: Upgrade MCP SDK

The SSE fix was merged December 2, 2025. Check if a newer MCP version includes fixes for Streamable HTTP:

```bash
uv add mcp@latest
```

### Option 2: Use SSE Transport Instead of Streamable HTTP

If the fix only applies to SSE:

```python
from pydantic_ai.mcp import MCPServerSSE

mcp = MCPServerSSE(
    url="https://lifesciences-research.fastmcp.app/sse",  # SSE endpoint
    id='lifesciences_mcp',
)
```

### Option 3: Use stdio Transport (Local Server)

Run MCP server locally with stdio transport:

```python
from pydantic_ai.mcp import MCPServerStdio

mcp = MCPServerStdio(
    command='uv',
    args=['run', 'python', '-m', 'lifesciences_mcp'],
    id='lifesciences_mcp',
)
```

### Option 4: Wait for Fix

Monitor [pydantic-ai #2818](https://github.com/pydantic/pydantic-ai/issues/2818) (milestone: 2026-01).

### Option 5: Run Without Temporal

Use standalone agents without Temporal durable execution:

```python
async with anchor_mcp:
    result = await anchor_agent.run("Resolve gene: TP53")
```

All 9 agents work correctly in this mode.

## Recommended Approach

**Use the one-shot pattern** (implemented in `src/cq14_temporal/`). This pattern:

1. Contains MCP lifecycle within each activity (avoids cancel scope bug)
2. Provides full Temporal durability (retries, workflow history, resumption)
3. Includes production-ready retry policies based on ADR-001 error codes
4. Supports CLI argument parsing and workflow resumption

### Future Options (When Upstream Bug is Fixed)

1. **Try Option 1**: Upgrade MCP SDK when Streamable HTTP fix is released
2. **If that works**: Migrate from one-shot pattern to TemporalAgent wrapper
3. **Monitor**: [pydantic-ai #2818](https://github.com/pydantic/pydantic-ai/issues/2818) (milestone: 2026-01)

## References

- [Pydantic AI Temporal Documentation](https://ai.pydantic.dev/durable_execution/temporal/)
- [Pydantic AI MCP Client Documentation](https://ai.pydantic.dev/mcp/client/)
- [Temporal.io Blog: Build durable AI agents with Pydantic](https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal)
- [GitHub Issue #2818](https://github.com/pydantic/pydantic-ai/issues/2818)
- [GitHub Issue #521](https://github.com/modelcontextprotocol/python-sdk/issues/521)
