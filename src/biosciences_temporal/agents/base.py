"""
Base utilities for CQ14 agents.

Provides the MCP client factory, shared configuration, and AgentRunner helper.
"""

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import AbstractToolset
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

# Default OpenRouter free-tier models for agents ($0 token spend).
# nvidia/nemotron-3.5-lightning:free supports both native tool calling and structured Pydantic output.
OPENROUTER_FREE_MODEL = (
    os.getenv("OPENROUTER_FREE_MODEL")
    or os.getenv("BIOSCIENCES_MODEL")
    or "nvidia/nemotron-3.5-lightning:free"
)
OPENROUTER_FALLBACK_MODEL = os.getenv("OPENROUTER_FALLBACK_MODEL") or "openrouter/free"
TYPESAFE_MODEL_NAME = os.getenv("TYPESAFE_MODEL_NAME") or "jev-latest"

# Alias preserved for package exports
MODEL = OPENROUTER_FREE_MODEL

# Higher usage limits for complex agents (default is 50 requests)
USAGE_LIMITS = UsageLimits(request_limit=100)


def create_mcp_client() -> MCPToolset:
    """Create MCP toolset using stdio transport.

    Uses stdio transport to avoid async cancel scope issues with Temporal.
    The server runs as a subprocess in the biosciences-mcp project.
    Environment variables are passed explicitly to ensure API keys are available.

    Returns:
        MCPToolset configured to run the biosciences gateway server.
    """
    # Pass parent environment to subprocess (includes API keys)
    env = os.environ.copy()

    transport = StdioTransport(
        command='uv',
        args=['run', 'fastmcp', 'run', GATEWAY_SERVER],
        cwd=BIOSCIENCES_MCP_PATH,
        env=env,
    )
    return MCPToolset(
        transport,
        id='biosciences_mcp',
        init_timeout=120.0,
        read_timeout=120.0,
    )


def create_model(model_name: str = MODEL, *, agent_name: str | None = None) -> Model:
    """Create the PydanticAI model with TypeSafe Jev, OpenRouter free-tier, and offline fallback.

    Resolution order:
    1. ``TestModel(call_tools=[])`` if ``USE_TEST_MODEL`` is truthy.
    2. ``TypeSafeModel(TYPESAFE_MODEL_NAME)`` if ``TYPESAFE_API_KEY`` is set.
    3. Per-agent override ``BIOSCIENCES_MODEL_<AGENT_NAME_UPPER>`` (if ``agent_name`` is given),
       otherwise ``model_name`` (``OPENROUTER_FREE_MODEL``), with fallback to
       ``OPENROUTER_FALLBACK_MODEL`` if ``OPENROUTER_API_KEY`` is set.
    4. ``TestModel(call_tools=[])`` fallback only when neither ``TYPESAFE_API_KEY`` nor
       ``OPENROUTER_API_KEY`` is present (offline development / tests).

    Args:
        model_name: Primary OpenRouter model identifier (default: MODEL constant).
        agent_name: Optional AgentRunner.name to look up BIOSCIENCES_MODEL_<AGENT_NAME_UPPER>.

    Returns:
        Configured Model (or FallbackModel / TestModel).
    """
    if os.getenv("USE_TEST_MODEL", "").lower() in ("1", "true", "yes"):
        return TestModel(call_tools=[])

    effective_model = model_name
    if agent_name:
        env_override = os.getenv(f"BIOSCIENCES_MODEL_{agent_name.upper()}")
        if env_override:
            effective_model = env_override

    models: list[Model] = []

    if os.getenv("TYPESAFE_API_KEY"):
        from pydantic_ai.models.typesafe import TypeSafeModel

        models.append(TypeSafeModel(TYPESAFE_MODEL_NAME))

    if os.getenv("OPENROUTER_API_KEY"):
        from pydantic_ai.models.openrouter import OpenRouterModel

        models.append(OpenRouterModel(effective_model))
        if OPENROUTER_FALLBACK_MODEL and OPENROUTER_FALLBACK_MODEL != effective_model:
            models.append(OpenRouterModel(OPENROUTER_FALLBACK_MODEL))

    if not models:
        return TestModel(call_tools=[])

    if len(models) == 1:
        return models[0]

    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(*models)


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
        toolsets: Sequence[AbstractToolset[Any]] | None = None,
    ):
        """Initialize the agent runner.

        Args:
            output_type: Pydantic model for structured output.
            instructions: System instructions for the agent.
            name: Agent name for Logfire span identification.
            metadata: Structured metadata for tracing.
            model: Model instance or identifier (default: gateway model from create_model()).
            usage_limits: Request limits (default: USAGE_LIMITS constant).
            toolsets: Optional toolsets override (e.g., ``FunctionToolset`` in unit tests).
                When omitted, live runs spawn ``create_mcp_client()`` while ``TestModel``
                runs use ``toolsets=[]`` so offline tests never invoke external MCP tools.
        """
        self.output_type = output_type
        self.instructions = instructions
        self.name = name
        self.metadata = metadata
        self.model = model
        self.usage_limits = usage_limits
        self.toolsets = toolsets

    @contextmanager
    def override(
        self,
        *,
        model: Model | str | None = None,
        toolsets: Sequence[AbstractToolset[Any]] | None = None,
    ) -> Iterator[None]:
        """Temporarily override the runner's model and/or toolsets for testing.

        Mirrors ``pydantic_ai.Agent.override()`` so tests can inject ``TestModel``,
        ``FunctionModel``, or ``FunctionToolset`` without monkeypatching module globals.
        """
        prev_model = self.model
        prev_toolsets = self.toolsets
        if model is not None:
            self.model = model
        if toolsets is not None:
            self.toolsets = toolsets
        try:
            yield
        finally:
            self.model = prev_model
            self.toolsets = prev_toolsets

    async def run(self, prompt: str, cq_id: str | None = None) -> T:
        """Execute the agent with MCP lifecycle contained.

        When an explicit ``toolsets`` override is configured or when the resolved model is
        ``TestModel``, ``create_mcp_client()`` is skipped so offline tests never spawn the
        live ``biosciences-mcp`` subprocess or call external biological APIs.

        Args:
            prompt: The prompt to send to the agent.
            cq_id: Override competency question ID for this run.

        Returns:
            The structured output from the agent.
        """
        resolved_model = (
            self.model if self.model is not None else create_model(agent_name=self.name)
        )

        if self.toolsets is not None or isinstance(resolved_model, TestModel):
            active_toolsets = list(self.toolsets) if self.toolsets is not None else []
            agent = Agent(
                resolved_model,
                output_type=self.output_type,
                instructions=self.instructions,
                name=self.name,
                toolsets=active_toolsets,
                metadata=self.metadata.to_dict(cq_id),
            )
            result = await agent.run(prompt, usage_limits=self.usage_limits)
            return result.output

        mcp = create_mcp_client()

        async with mcp:
            agent = Agent(
                resolved_model,
                output_type=self.output_type,
                instructions=self.instructions,
                name=self.name,
                toolsets=[mcp],
                metadata=self.metadata.to_dict(cq_id),
            )
            result = await agent.run(prompt, usage_limits=self.usage_limits)
            return result.output
