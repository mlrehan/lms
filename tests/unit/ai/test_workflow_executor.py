"""Unit tests for Multi-Step Workflow Engine and rollback mechanics."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.workflows.executor import (
    StepStatus,
    WorkflowExecutionContext,
    WorkflowExecutor,
    WorkflowResult,
    WorkflowStep,
)
from backend.models.identity.user import User


def make_context() -> WorkflowExecutionContext:
    return WorkflowExecutionContext(
        user=User(id=1, username="testuser", slug="testuser", hashed_password="pw"),
        session=MagicMock(),
        workflow_id="wf_test_1",
        idempotency_key="idemp_12345",
    )


def test_workflow_successful_execution():
    async def run_test():
        async def step1(data, ctx):
            return {"step1_val": 42}

        async def step2(data, ctx):
            return {"step2_val": data["step1_val"] * 2}

        executor = WorkflowExecutor(
            workflow_id="wf_success",
            steps=[
                WorkflowStep(name="step_one", description="First", action=step1),
                WorkflowStep(name="step_two", description="Second", action=step2),
            ],
        )

        ctx = make_context()
        res = await executor.execute(context=ctx, initial_payload={"init": True})

        assert res.success is True
        assert res.completed_steps == ["step_one", "step_two"]
        assert res.failed_step is None
        assert res.outputs["step_two"]["step2_val"] == 84

    asyncio.run(run_test())


def test_workflow_failure_triggers_reverse_rollback():
    async def run_test():
        rollback_called = []

        async def step1_action(data, ctx):
            return {"resource_id": "res-99"}

        async def step1_rollback(output, ctx):
            rollback_called.append(output["resource_id"])

        async def step2_action(data, ctx):
            raise RuntimeError("Database deadlock simulated in step 2")

        executor = WorkflowExecutor(
            workflow_id="wf_rollback",
            steps=[
                WorkflowStep(
                    name="create_resource",
                    description="Create resource",
                    action=step1_action,
                    rollback=step1_rollback,
                ),
                WorkflowStep(
                    name="publish_resource",
                    description="Publish resource",
                    action=step2_action,
                ),
            ],
        )

        ctx = make_context()
        res = await executor.execute(context=ctx)

        assert res.success is False
        assert res.failed_step == "publish_resource"
        assert "deadlock" in res.error_message
        # Verify rollback handler was invoked for step 1 with its output!
        assert rollback_called == ["res-99"]

    asyncio.run(run_test())


def test_workflow_timeout_triggers_rollback():
    async def run_test():
        rollback_called = []

        async def step1_action(data, ctx):
            return {"step1": "ok"}

        async def step1_rollback(output, ctx):
            rollback_called.append("step1_rolled_back")

        async def step2_hanging_action(data, ctx):
            await asyncio.sleep(2.0)  # Will exceed 0.2s timeout
            return {"step2": "never"}

        executor = WorkflowExecutor(
            workflow_id="wf_timeout",
            steps=[
                WorkflowStep(
                    name="step_one",
                    description="Step 1",
                    action=step1_action,
                    rollback=step1_rollback,
                ),
                WorkflowStep(
                    name="step_hanging",
                    description="Step Hanging",
                    action=step2_hanging_action,
                ),
            ],
            timeout_seconds=0.2,
        )

        ctx = make_context()
        res = await executor.execute(context=ctx)

        assert res.success is False
        assert res.failed_step == "TIMEOUT"
        assert "timeout" in res.error_message.lower()
        assert rollback_called == ["step1_rolled_back"]

    asyncio.run(run_test())

