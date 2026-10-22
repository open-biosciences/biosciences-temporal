"""
Base utilities for CQ14 agents.

Provides the MCP client factory, shared configuration, and AgentRunner helper.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.gateway import gateway_provider
from pydantic_ai.usage import UsageLimits


# --- Configuration ---

def _find_sibling_repo() -> str:
    """Find biosciences-mcp as sibling to this repo's root.

    Resolution order:
    1. BIOSCIENCES_MCP_PATH environment variable (explicit override)
    2. Sibling directory (repos cloned to same parent)

    Returns:
        Path to the biosciences-mcp repository.

    Raises:
        FileNotFoundError: If repository cannot be found with helpful instructions.
    """
    # Priority 1: Environment variable
    if env_path := os.environ.get("BIOSCIENCES_MCP_PATH"):
        path = Path(env_path).resolve()
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"BIOSCIENCES_MCP_PATH={env_path} does not exist")

    # Priority 2: Sibling directory (repos cloned to same parent)
    # This file is at: repo_root/src/biosciences_temporal/agents/base.py
    repo_root = Path(__file__).resolve().parents[3]
    sibling_path = repo_root.parent / "biosciences-mcp"

    if sibling_path.exists():
        return str(sibling_path)

    raise FileNotFoundError(
        f"biosciences-mcp not found at {sibling_path}\n\n"
        f"Either:\n"
        f"  1. Clone biosciences-mcp next to biosciences-temporal:\n"
        f"     cd {repo_root.parent}\n"
        f"     git clone https://github.com/donbr/biosciences-mcp.git\n\n"
        f"  2. Set BIOSCIENCES_MCP_PATH environment variable:\n"
        f"     export BIOSCIENCES_MCP_PATH=/path/to/biosciences-mcp"
    )


BIOSCIENCES_MCP_PATH = _find_sibling_repo()

# Gateway server module path
GATEWAY_SERVER = "src/biosciences_mcp/servers/gateway.py"

# Default model for agents (served through the Pydantic AI Gateway).
# Override with BIOSCIENCES_MODEL; read once at import time.
MODEL = os.getenv("BIOSCIENCES_MODEL") or "claude-sonnet-5"

# Pydantic AI Gateway routing: requests go to GATEWAY_BASE_URL/GATEWAY_ROUTE.
# The upstream provider selects the client transport; the route only names the
# gateway's provider path. base_url is passed explicitly so a route-qualified
# PYDANTIC_AI_GATEWAY_BASE_URL in the environment can't double the path.
GATEWAY_UPSTREAM_PROVIDER = "anthropic"
GATEWAY_ROUTE = "anthropic-provider"
GATEWAY_BASE_URL = "https://gateway-us.pydantic.dev/proxy"

# Higher usage limits for complex agents (default is 50 requests)
USAGE_LIMITS = UsageLimits(request_limit=100)


def create_mcp_client() -> MCPServerStdio:
    """Create MCP client using stdio transport.

    Uses stdio transport to avoid async cancel scope issues with Temporal.
    The server runs as a subprocess in the biosciences-mcp project.
    Environment variables are passed explicitly to ensure API keys are available.

    Returns:
        MCPServerStdio configured to run the biosciences gateway server.
    """
    # Pass parent environment to subprocess (includes API keys)
    env = os.environ.copy()

    return MCPServerStdio(
        command='uv',
        args=['run', 'fastmcp', 'run', GATEWAY_SERVER],
        cwd=BIOSCIENCES_MCP_PATH,
        env=env,
        id='biosciences_mcp',
        timeout=120.0,
    )


def create_model(model_name: str = MODEL) -> Model:
    """Create a model that sends requests through the Pydantic AI Gateway.

    Reads the gateway key from PYDANTIC_AI_GATEWAY_API_KEY.

    Args:
        model_name: Upstream model identifier (default: MODEL constant).

    Returns:
        AnthropicModel backed by the gateway provider.
    """
    provider = gateway_provider(
        GATEWAY_UPSTREAM_PROVIDER,
        route=GATEWAY_ROUTE,
        base_url=GATEWAY_BASE_URL,
    )
    return AnthropicModel(model_name, provider=provider)


# --- Agent Metadata ---

@dataclass
class AgentMetadata:
    """Structured metadata for agent spans in Logfire.

    See docs/metadata-spec.md for valid values.
    """
    phase: str       # anchor, enrich, expand, traverse, validate
    action: str      # resolve, protein, interactions, drugs, trials, gene, drug, trial, sl
    entity_type: str # gene, protein, interaction, compound, trial, gene_pair
    source: str      # HGNC, UniProt, STRING, BioGRID, ChEMBL, ClinicalTrials.gov
    cq_id: str = "cq14"

    def to_dict(self, cq_id: str | None = None) -> dict:
        """Convert to metadata dict for PydanticAI Agent.

        Args:
            cq_id: Override the default cq_id if provided.

        Returns:
            Dictionary suitable for Agent metadata parameter.
        """
        return {
            "phase": self.phase,
            "action": self.action,
            "entity_type": self.entity_type,
            "source": self.source,
            "cq_id": cq_id or self.cq_id,
        }


# --- Agent Runner ---

T = TypeVar("T")


class AgentRunner(Generic[T]):
    """Factory for running PydanticAI agents with MCP toolsets.

    Reduces boilerplate by encapsulating:
    - MCP client lifecycle management
    - Agent construction with consistent configuration
    - Metadata and usage limits

    Example:
        >>> runner = AgentRunner(
        ...     output_type=GeneInfo,
        ...     instructions="Resolve gene symbols...",
        ...     name="anchor_resolve",
        ...     metadata=AgentMetadata(
        ...         phase="anchor",
        ...         action="resolve",
        ...         entity_type="gene",
        ...         source="HGNC"
        ...     ),
        ... )
        >>> result = await runner.run("Resolve gene: TP53")
    """

    def __init__(
        self,
        output_type: type[T],
        instructions: str,
        name: str,
        metadata: AgentMetadata,
        model: Model | str | None = None,
        usage_limits: UsageLimits = USAGE_LIMITS,
    ):
        """Initialize the agent runner.

        Args:
            output_type: Pydantic model for structured output.
            instructions: System instructions for the agent.
            name: Agent name for Logfire span identification.
            metadata: Structured metadata for tracing.
            model: Model instance or identifier (default: gateway model from create_model()).
            usage_limits: Request limits (default: USAGE_LIMITS constant).
        """
        self.output_type = output_type
        self.instructions = instructions
        self.name = name
        self.metadata = metadata
        self.model = model
        self.usage_limits = usage_limits

    async def run(self, prompt: str, cq_id: str | None = None) -> T:
        """Execute the agent with MCP lifecycle contained.

        The MCP client is created, used, and closed within this single call,
        ensuring the anyio cancel scope is properly managed within one task.

        Args:
            prompt: The prompt to send to the agent.
            cq_id: Override competency question ID for this run.

        Returns:
            The structured output from the agent.
        """
        mcp = create_mcp_client()

        async with mcp:
            agent = Agent(
                self.model if self.model is not None else create_model(),
                output_type=self.output_type,
                instructions=self.instructions,
                name=self.name,
                toolsets=[mcp],
                metadata=self.metadata.to_dict(cq_id),
            )
            result = await agent.run(prompt, usage_limits=self.usage_limits)
            return result.output
