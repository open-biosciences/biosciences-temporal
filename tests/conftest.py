"""Global pytest configuration and LLM/MCP isolation guards."""

import pydantic_ai.models
import pytest

# Block any accidental real LLM HTTP requests during offline unit tests.
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def isolate_model_and_telemetry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear live API keys by default so unit tests stay deterministic and offline."""
    for var in (
        "OPENROUTER_API_KEY",
        "TYPESAFE_API_KEY",
        "LOGFIRE_TOKEN",
        "USE_TEST_MODEL",
        "BIOSCIENCES_MODEL_ANCHOR_RESOLVE",
    ):
        monkeypatch.delenv(var, raising=False)
