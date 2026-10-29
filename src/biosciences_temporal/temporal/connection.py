"""Single place that connects to Temporal, so client and worker share Logfire and PydanticAI plugins."""

import os

import logfire
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import LogfirePlugin, PydanticAIPlugin
from temporalio.client import Client

from ..config import TEMPORAL_ADDRESS

SERVICE_NAME = "biosciences-temporal"


def setup_logfire() -> logfire.Logfire:
    """Configure Logfire once for biosciences-temporal without overwriting existing host config.

    Preserves any prior ``logfire.configure()`` call (such as ``service_name="biosciences-temporal"``
    or ``send_to_logfire=False``) while ensuring standalone ``connect()`` callers also get the
    project defaults and PydanticAI instrumentation.
    """
    instance = logfire.DEFAULT_LOGFIRE_INSTANCE
    if not getattr(instance.config, "_initialized", False):
        token = os.getenv("LOGFIRE_TOKEN")
        if token:
            instance = logfire.configure(token=token, service_name=SERVICE_NAME)
        else:
            instance = logfire.configure(send_to_logfire=False, service_name=SERVICE_NAME)

    if getattr(Agent, "_instrument_default", False) is False:
        instance.instrument_pydantic_ai()

    return instance


async def connect(address: str = TEMPORAL_ADDRESS) -> Client:
    """Connect a Temporal client with PydanticAI and Logfire OpenTelemetry plugins.

    PydanticAIPlugin sets the Pydantic data converter. LogfirePlugin adds Temporal's
    OpenTelemetry TracingInterceptor (replay-safe) on the already-configured Logfire
    instance, so a CQ14 workflow execution is one unified trace:
    workflow -> activities -> PydanticAI agent runs -> OpenRouter / MCP spans.
    """
    return await Client.connect(
        address,
        plugins=[
            PydanticAIPlugin(),
            LogfirePlugin(setup_logfire=setup_logfire, metrics=False),
        ],
    )


