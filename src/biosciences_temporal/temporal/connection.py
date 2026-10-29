"""Single place that connects to Temporal, so client and worker share Logfire and PydanticAI plugins."""

from pydantic_ai.durable_exec.temporal import LogfirePlugin, PydanticAIPlugin
from temporalio.client import Client

from ..config import TEMPORAL_ADDRESS


async def connect(address: str = TEMPORAL_ADDRESS) -> Client:
    """Connect a Temporal client with PydanticAI and Logfire OpenTelemetry plugins.

    PydanticAIPlugin sets the Pydantic data converter. LogfirePlugin adds Temporal's
    OpenTelemetry TracingInterceptor (replay-safe) on the already-configured Logfire
    instance, so a CQ14 workflow execution is one unified trace:
    workflow -> activities -> PydanticAI agent runs -> OpenRouter / MCP spans.
    """
    return await Client.connect(
        address,
        plugins=[PydanticAIPlugin(), LogfirePlugin(metrics=False)],
    )

