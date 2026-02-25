# biosciences-temporal

PydanticAI agents with Temporal.io durable workflow execution for the [Open Biosciences](https://github.com/open-biosciences) platform. Follows a "PydanticAI First, Temporal Second" design -- agents are fully testable as standalone units before being wrapped in durable workflows.

## Status

**Pending Wave 3 (Orchestration) migration.** Content is being migrated from the predecessor `lifesciences-temporal` repository.

## What's Coming

After migration, this repository will contain:

- **PydanticAI standalone agents** for individual research tasks
- **Temporal workflow definitions** composing agents into durable pipelines
- **Temporal activity definitions** wrapping MCP tool calls
- **Worker configuration** with retry policies and timeouts
- **Docker Compose** for Temporal server + Neo4j local environment
- **CQ14 pipeline** -- a 5-phase research workflow:
  1. Anchor -- resolve seed entities
  2. Enrich -- gather annotations and metadata
  3. Expand -- discover related entities
  4. Traverse -- follow drug and trial relationships
  5. Validate -- cross-source verification

The design ensures agents can be tested without Temporal infrastructure, then composed into fault-tolerant workflows with automatic retries and state persistence.

## Agent Ownership

Maintained by the **Temporal Engineer** agent (Agent 7). See [AGENTS.md](../biosciences-program/AGENTS.md) for full team definitions.

## Dependencies

| Direction | Repository | Relationship |
|-----------|------------|--------------|
| Upstream | biosciences-mcp | Activities call MCP tools via stdio transport |

## Related Repositories

- [biosciences-mcp](https://github.com/open-biosciences/biosciences-mcp) -- FastMCP API servers
- [biosciences-deepagents](https://github.com/open-biosciences/biosciences-deepagents) -- LangGraph multi-agent system
- [biosciences-memory](https://github.com/open-biosciences/biosciences-memory) -- Knowledge graph layer

## License

MIT
