"""Multi-Step Composite Workflow Engine.

Executes deterministic directed execution graphs (DAGs) for multi-step composite
instructions with checkpoints, execution timeouts, and rollback handlers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AppError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.user import User

logger = get_logger(__name__)


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class WorkflowStep:
    """A single deterministic checkpointed step in a workflow."""

    name: str
    description: str
    action: Callable[[dict[str, Any], WorkflowExecutionContext], Awaitable[dict[str, Any]]]
    rollback: Callable[[dict[str, Any], WorkflowExecutionContext], Awaitable[None]] | None = None
    status: StepStatus = StepStatus.PENDING
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class WorkflowExecutionContext:
    """Runtime context passed across workflow steps."""

    user: User
    session: AsyncSession
    workflow_id: str
    idempotency_key: str
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """Execution outcome of a multi-step workflow."""

    workflow_id: str
    success: bool
    completed_steps: list[str]
    failed_step: str | None = None
    error_message: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)


class WorkflowExecutor:
    """Executes a linear sequence of steps with checkpointing and rollback protection."""

    def __init__(
        self,
        *,
        workflow_id: str,
        steps: list[WorkflowStep],
        timeout_seconds: float = 60.0,
    ) -> None:
        self.workflow_id = workflow_id
        self.steps = steps
        self.timeout_seconds = timeout_seconds

    async def execute(
        self,
        *,
        context: WorkflowExecutionContext,
        initial_payload: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Run all steps sequentially. If any step fails, triggers reverse rollback."""
        logger.info(
            "Starting workflow %s with %d steps for user %s",
            self.workflow_id,
            len(self.steps),
            context.user.public_id,
        )

        completed_steps: list[WorkflowStep] = []
        current_data = dict(initial_payload or {})
        all_outputs: dict[str, Any] = {}

        try:
            async with asyncio.timeout(self.timeout_seconds):
                for step in self.steps:
                    logger.info("Executing workflow step: %s", step.name)
                    step.status = StepStatus.RUNNING

                    try:
                        step_output = await step.action(current_data, context)
                        step.status = StepStatus.COMPLETED
                        step.output = step_output
                        all_outputs[step.name] = step_output
                        completed_steps.append(step)

                        # Accumulate output for subsequent steps
                        current_data.update(step_output)
                        context.state[step.name] = step_output

                    except Exception as step_exc:
                        step.status = StepStatus.FAILED
                        step.error = str(step_exc)
                        logger.error(
                            "Step '%s' failed in workflow %s: %s",
                            step.name,
                            self.workflow_id,
                            step_exc,
                        )
                        # Trigger reverse rollback of completed steps
                        await self._rollback_completed_steps(completed_steps, context)
                        return WorkflowResult(
                            workflow_id=self.workflow_id,
                            success=False,
                            completed_steps=[s.name for s in completed_steps],
                            failed_step=step.name,
                            error_message=str(step_exc),
                            outputs=all_outputs,
                        )

            return WorkflowResult(
                workflow_id=self.workflow_id,
                success=True,
                completed_steps=[s.name for s in self.steps],
                outputs=all_outputs,
            )

        except TimeoutError:
            logger.error("Workflow %s exceeded timeout of %fs", self.workflow_id, self.timeout_seconds)
            await self._rollback_completed_steps(completed_steps, context)
            return WorkflowResult(
                workflow_id=self.workflow_id,
                success=False,
                completed_steps=[s.name for s in completed_steps],
                failed_step="TIMEOUT",
                error_message=f"Workflow exceeded execution timeout of {self.timeout_seconds}s.",
                outputs=all_outputs,
            )

    async def _rollback_completed_steps(
        self,
        completed_steps: list[WorkflowStep],
        context: WorkflowExecutionContext,
    ) -> None:
        """Roll back completed steps in reverse order to preserve data integrity."""
        for step in reversed(completed_steps):
            if step.rollback:
                try:
                    logger.warning("Rolling back workflow step: %s", step.name)
                    await step.rollback(step.output, context)
                    step.status = StepStatus.ROLLED_BACK
                except Exception as rb_exc:
                    logger.critical(
                        "Rollback handler failed for step '%s': %s",
                        step.name,
                        rb_exc,
                    )
