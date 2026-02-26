"""
Start the Temporal worker for CQ14 workflow.

This script starts the worker that polls the task queue and executes
workflows and activities.

Usage:
    uv run python -m src.biosciences_temporal.scripts.run_worker
"""

# Configure Logfire before other imports that use Pydantic AI
import logfire

logfire.configure()
logfire.instrument_pydantic_ai()

import asyncio
import os
import sys

# Add parent to path for relative imports when running as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.biosciences_temporal.temporal.worker import main


if __name__ == "__main__":
    asyncio.run(main())
