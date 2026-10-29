"""Tests for Logfire configuration preservation, model resolution, and offline AgentRunner testing."""

import asyncio

import logfire
import pytest
from pydantic_ai.durable_exec.temporal import LogfirePlugin
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.typesafe import TypeSafeModel
from pydantic_ai.toolsets import FunctionToolset

from biosciences_temporal.agents.base import create_model
from biosciences_temporal.agents.models import GeneInfo
from biosciences_temporal.agents.resolve import _runner as resolve_gene_runner
from biosciences_temporal.agents.resolve import resolve_gene
from biosciences_temporal.temporal.connection import SERVICE_NAME, setup_logfire


def test_setup_logfire_and_plugin_preserve_host_configuration() -> None:
    """LogfirePlugin(setup_logfire=setup_logfire) preserves service_name and send_to_logfire=False."""
    logfire.configure(send_to_logfire=False, service_name=SERVICE_NAME)
    instance = setup_logfire()

    assert instance.config.service_name == SERVICE_NAME
    assert instance.config.send_to_logfire is False

    plugin = LogfirePlugin(setup_logfire=setup_logfire, metrics=False)
    resolved = plugin._setup_replay_safe_instrumentation()

    assert resolved is instance
    assert resolved.config.service_name == SERVICE_NAME
    assert resolved.config.send_to_logfire is False


def test_create_model_offline_returns_test_model_without_tool_calls() -> None:
    """Without API keys, create_model returns TestModel(call_tools=[]) for safe offline execution."""
    model = create_model(agent_name="anchor_resolve")
    assert isinstance(model, TestModel)
    assert model.call_tools == []


def test_create_model_with_typesafe_and_openrouter_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With TYPESAFE_API_KEY and OPENROUTER_API_KEY set, create_model builds TypeSafeModel + OpenRouterModel."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("BIOSCIENCES_MODEL_ANCHOR_RESOLVE", "google/gemma-4-31b-it:free")

    # TypeSafe + OpenRouter chain with per-agent override
    model = create_model(agent_name="anchor_resolve")
    assert isinstance(model, FallbackModel)
    assert len(model.models) == 3
    assert isinstance(model.models[0], TypeSafeModel)
    assert model.models[0].model_name == "jev-latest"
    assert isinstance(model.models[1], OpenRouterModel)
    assert model.models[1].model_name == "google/gemma-4-31b-it:free"
    assert isinstance(model.models[2], OpenRouterModel)
    assert model.models[2].model_name == "openrouter/free"


def test_create_model_typesafe_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only TYPESAFE_API_KEY set, create_model returns TypeSafeModel directly (no silent fallback)."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")

    model = create_model()
    assert isinstance(model, TypeSafeModel)
    assert model.model_name == "jev-latest"


async def test_agent_runner_offline_skips_mcp_and_returns_structured_output() -> None:
    """In offline mode, AgentRunner uses TestModel(call_tools=[]) and never spawns MCPToolset."""
    result = await resolve_gene("TP53")
    assert isinstance(result, GeneInfo)


async def test_agent_runner_override_with_function_toolset() -> None:
    """AgentRunner.override() injects an in-memory FunctionToolset without monkeypatching."""
    called_with: list[str] = []
    toolset = FunctionToolset()

    @toolset.tool_plain
    def lookup_hgnc_gene(symbol: str) -> dict[str, str]:
        """Mock in-memory HGNC lookup tool."""
        called_with.append(symbol)
        return {"hgnc_id": "HGNC:11998", "symbol": symbol}

    with resolve_gene_runner.override(
        model=TestModel(call_tools=["lookup_hgnc_gene"]),
        toolsets=[toolset],
    ):
        assert resolve_gene_runner.model is None
        result = await resolve_gene_runner.run("Resolve gene: TP53")

    assert isinstance(result, GeneInfo)
    assert len(called_with) == 1


async def test_agent_runner_override_is_context_local_across_concurrent_tasks() -> None:
    """Concurrent tasks on the same AgentRunner singleton keep isolated ContextVar overrides."""
    task_a_calls: list[str] = []
    toolset_a = FunctionToolset()

    @toolset_a.tool_plain
    def tool_only_for_task_a(symbol: str) -> dict[str, str]:
        task_a_calls.append(symbol)
        return {"hgnc_id": "HGNC:11998", "symbol": symbol}

    async def run_with_tool_override() -> GeneInfo:
        with resolve_gene_runner.override(
            model=TestModel(call_tools=["tool_only_for_task_a"]),
            toolsets=[toolset_a],
        ):
            await asyncio.sleep(0.01)
            return await resolve_gene("TP53")

    async def run_without_tool_override() -> GeneInfo:
        await asyncio.sleep(0.005)
        return await resolve_gene("TYMS")

    res_a, res_b = await asyncio.gather(
        run_with_tool_override(),
        run_without_tool_override(),
    )

    assert isinstance(res_a, GeneInfo)
    assert isinstance(res_b, GeneInfo)
    assert len(task_a_calls) == 1


async def test_agent_runner_rejects_empty_toolset_override_with_production_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty toolsets=[] override is rejected when a production model is configured."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    prod_model = OpenRouterModel("nvidia/nemotron-3.5-lightning:free")

    with (
        resolve_gene_runner.override(model=prod_model, toolsets=[]),
        pytest.raises(ValueError, match="cannot run a non-test model with an empty"),
    ):
        await resolve_gene_runner.run("Resolve gene: TP53")

