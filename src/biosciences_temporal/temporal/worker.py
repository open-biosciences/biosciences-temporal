"""
Temporal worker for CQ14 workflow.

Registers workflows and activities, then polls the task queue for work.

NOTE: Workflow sandboxing is disabled because pydantic_ai imports anyio/sniffio
which are not compatible with Temporal's deterministic sandbox. The workflow
itself is deterministic (just orchestrates activity calls), and all
non-deterministic work (LLM calls, API calls) happens in activities.
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from ..config import TASK_QUEUE
from .activities import ALL_ACTIVITIES
from .workflows import CQ14Workflow


async def main():
    """Start the Temporal worker."""
    print(f"Connecting to Temporal at localhost:7233...")
    client = await Client.connect("localhost:7233")

    print(f"Starting worker on task queue: {TASK_QUEUE}")
    print(f"Registered workflow: CQ14Workflow")
    print(f"Registered activities: {len(ALL_ACTIVITIES)}")

    # Use UnsandboxedWorkflowRunner because pydantic_ai imports anyio/sniffio
    # which are incompatible with Temporal's deterministic sandbox.
    # Our workflow is deterministic - all non-deterministic work is in activities.
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CQ14Workflow],
        activities=ALL_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )

    print("Worker running (sandbox disabled). Press Ctrl+C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
