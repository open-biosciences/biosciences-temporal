"""
Start the Temporal worker for CQ14 workflow.

This script starts the worker that polls the task queue and executes
workflows and activities.

Usage:
    uv run python -m src.biosciences_temporal.scripts.run_worker
"""

# Load .env first so LOGFIRE_TOKEN, OPENROUTER_API_KEY, and model overrides are set
# before Logfire and the agents see them.
# override=True: .env wins over stale shell exports.
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

# Add parent to path for relative imports when running as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.biosciences_temporal.temporal.connection import setup_logfire  # noqa: E402

setup_logfire()

from src.biosciences_temporal.temporal.worker import main  # noqa: E402


if __name__ == "__main__":
    asyncio.run(main())
