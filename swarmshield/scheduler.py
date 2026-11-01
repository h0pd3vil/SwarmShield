"""Virtual-clock scheduler for synthetic information-processing decisions."""

from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass
class ScheduledTask:
    task_id: str
    task_type: str
    created_at: int
    deadline: int
    priority: int
    processing_cost: int
    information_time: int
    remaining_cost: int
    status: str = "queued"
    started_at: int | None = None
    completed_at: int | None = None


class DecisionScheduler:
    """Schedules logical work units; it makes no wall-clock guarantees."""

    def __init__(
        self,
        rng: random.Random,
        policy: str,
        processing_capacity_per_step: int,
        queue_capacity: int,
        min_deadline_steps: int,
        max_deadline_steps: int,
        max_processing_cost: int,
        max_priority: int,
    ) -> None:
        if policy not in {"fixed-priority", "edf"}:
            raise ValueError("policy must be 'fixed-priority' or 'edf'")
        self._rng = rng
        self.policy = policy
        self.processing_capacity_per_step = processing_capacity_per_step
        self.queue_capacity = queue_capacity
        self.min_deadline_steps = min_deadline_steps
        self.max_deadline_steps = max_deadline_steps
        self.max_processing_cost = max_processing_cost
        self.max_priority = max_priority
        self._active: list[ScheduledTask] = []
        self.tasks: list[ScheduledTask] = []
        self.events: list[dict[str, object]] = []
        self.backlog_by_step: list[int] = []
        self.max_backlog = 0

    def submit(
        self,
        task_id: str,
        task_type: str,
        created_at: int,
        information_time: int,
    ) -> bool:
        processing_cost = self._rng.randint(1, self.max_processing_cost)
        priority = self._rng.randint(1, self.max_priority)
        deadline = created_at + self._rng.randint(
            self.min_deadline_steps,
            self.max_deadline_steps,
        )
        task = ScheduledTask(
            task_id=task_id,
            task_type=task_type,
            created_at=created_at,
            deadline=deadline,
            priority=priority,
            processing_cost=processing_cost,
            information_time=information_time,
            remaining_cost=processing_cost,
        )
        self.tasks.append(task)
        self._record(task, created_at, "task_created", "queued")

        if len(self._active) >= self.queue_capacity:
            task.status = "dropped"
            self._record(task, created_at, "task_dropped", "queue_overload")
            return False

        self._active.append(task)
        self.max_backlog = max(self.max_backlog, len(self._active))
        return True

    def tick(self, current_step: int) -> list[ScheduledTask]:
        """Advance logical processing by one simulation step."""
        self.expire_before(current_step)

        remaining_capacity = self.processing_capacity_per_step
        completed: list[ScheduledTask] = []
        while self._active and remaining_capacity > 0:
            task = min(self._active, key=self._sort_key)
            if task.started_at is None:
                task.started_at = current_step
                task.status = "running"
                self._record(task, current_step, "task_started", "")

            work_done = min(task.remaining_cost, remaining_capacity)
            task.remaining_cost -= work_done
            remaining_capacity -= work_done

            if task.remaining_cost == 0:
                task.status = "completed"
                task.completed_at = current_step
                self._active.remove(task)
                completed.append(task)
                self._record(task, current_step, "task_completed", "on_time")

        self.backlog_by_step.append(len(self._active))
        self.max_backlog = max(self.max_backlog, len(self._active))
        return completed

    def expire_before(self, current_step: int) -> None:
        """Expire overdue work before new arrivals compete for queue capacity."""
        for task in tuple(self._active):
            if current_step > task.deadline:
                task.status = "expired"
                self._active.remove(task)
                self._record(task, current_step, "task_expired", "deadline_passed")

    def record_pending(self, horizon: int) -> None:
        for task in sorted(tuple(self._active), key=lambda queued: (queued.deadline, queued.task_id)):
            self._active.remove(task)
            if task.deadline <= horizon:
                task.status = "expired"
                self._record(task, horizon, "task_expired", "deadline_passed_at_horizon")
            else:
                task.status = "pending_at_horizon"
                self._record(task, horizon, "task_pending", "simulation_horizon")

    def record_decision_result(self, task: ScheduledTask, details: str) -> None:
        if task.completed_at is None:
            raise ValueError("Only a completed task can record a decision result")
        self._record(task, task.completed_at, "decision_applied", details)

    def eligible_task_count(self, horizon: int) -> int:
        return sum(task.deadline <= horizon for task in self.tasks)

    def deadline_miss_count(self, horizon: int) -> int:
        return sum(
            task.deadline <= horizon and task.status in {"expired", "dropped"}
            for task in self.tasks
        )

    @property
    def active_task_count(self) -> int:
        return len(self._active)

    def _sort_key(self, task: ScheduledTask) -> tuple[object, ...]:
        common_tiebreakers = (-task.priority, task.created_at, task.task_id)
        if self.policy == "edf":
            return (task.deadline, *common_tiebreakers)
        return (-task.priority, task.deadline, task.created_at, task.task_id)

    def _record(
        self,
        task: ScheduledTask,
        step: int,
        event_type: str,
        details: str,
    ) -> None:
        self.events.append(
            {
                "step": step,
                "event_type": event_type,
                "message_id": "",
                "sender_id": "",
                "recipient_id": "",
                "entity_id": "",
                "details": details,
                "copy_index": 0,
                "task_id": task.task_id,
                "task_type": task.task_type,
                "deadline": task.deadline,
                "priority": task.priority,
                "processing_cost": task.processing_cost,
                "remaining_cost": task.remaining_cost,
                "information_time": task.information_time,
            }
        )
