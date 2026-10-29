"""
Temporal worker for CQ14 workflow.

Registers workflows and activities with Temporal's deterministic workflow sandbox
(`SandboxedWorkflowRunner`), then polls the task queue for work.
"""

import asyncio

from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from ..config import TASK_QUEUE, TEMPORAL_ADDRESS
from .activities import ALL_ACTIVITIES
from .connection import connect
from .workflows import CQ14Workflow

# Pass through config and beartype (used by fastmcp) alongside PydanticAIPlugin's
# automatic passthroughs so CQ14Workflow runs inside Temporal's deterministic sandbox.
WORKFLOW_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "biosciences_temporal.config", "beartype"
    )
)


async def main():
    """Start the Temporal worker."""
    print(f"Connecting to Temporal at {TEMPORAL_ADDRESS}...")
    client = await connect(TEMPORAL_ADDRESS)

    print(f"Starting worker on task queue: {TASK_QUEUE}")
    print("Registered workflow: CQ14Workflow")
    print(f"Registered activities: {len(ALL_ACTIVITIES)}")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CQ14Workflow],
        activities=ALL_ACTIVITIES,
        workflow_runner=WORKFLOW_RUNNER,
    )

    print("Worker running (sandbox enabled). Press Ctrl+C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
