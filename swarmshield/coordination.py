"""Abstract resource assignment for synthetic review tasks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass
class CoordinationTask:
    task_id: str
    entity_id: str
    created_at: int
    deadline: int
    status: str = "queued"
    resource_id: str | None = None
    assigned_at: int | None = None
    completes_at: int | None = None
    completed_at: int | None = None


class CoordinationManager:
    """Assigns non-physical review tasks while enforcing resource capacity."""

    def __init__(
        self,
        resource_ids: tuple[str, ...],
        mode: str,
        capacity_per_resource: int,
        task_duration_steps: int,
        task_deadline_steps: int,
        queue_capacity: int,
    ) -> None:
        if not resource_ids:
            raise ValueError("at least one resource is required")
        if mode not in {"centralized", "decentralized"}:
            raise ValueError("mode must be 'centralized' or 'decentralized'")
        if capacity_per_resource <= 0 or task_duration_steps <= 0 or queue_capacity <= 0:
            raise ValueError("resource capacity, task duration, and queue capacity must be positive")
        if task_deadline_steps < 0:
            raise ValueError("task deadline steps cannot be negative")

        self.resource_ids = tuple(sorted(resource_ids))
        self.mode = mode
        self.capacity_per_resource = capacity_per_resource
        self.task_duration_steps = task_duration_steps
        self.task_deadline_steps = task_deadline_steps
        self.queue_capacity = queue_capacity
        self.tasks: list[CoordinationTask] = []
        self.events: list[dict[str, object]] = []
        self._task_by_entity: dict[str, CoordinationTask] = {}
        self._next_task_number = 1
        self.conflict_count = 0
        self.capacity_violation_count = 0
        self.max_resource_load = 0

    def request_review(self, entity_id: str, step: int) -> CoordinationTask | None:
        """Create one generic review task the first time an entity is tracked."""
        if entity_id in self._task_by_entity:
            return None

        task = CoordinationTask(
            task_id=f"review-{self._next_task_number:06d}",
            entity_id=entity_id,
            created_at=step,
            deadline=step + self.task_deadline_steps,
        )
        self._next_task_number += 1
        self._task_by_entity[entity_id] = task
        self.tasks.append(task)
        self._record(task, step, "coordination_task_created", "abstract_review")

        queued = sum(existing.status == "queued" for existing in self.tasks)
        if queued > self.queue_capacity:
            task.status = "dropped"
            self._record(task, step, "coordination_task_dropped", "queue_overload")
            return task

        self._try_assign(task, step)
        return task

    def tick(self, step: int) -> None:
        for task in self.tasks:
            if task.status != "assigned":
                continue
            if task.completes_at is not None and task.completes_at <= step and task.completes_at <= task.deadline:
                task.status = "completed"
                task.completed_at = step
                self._record(task, step, "coordination_task_completed", "abstract_outcome")
            elif step > task.deadline:
                task.status = "expired"
                self._record(task, step, "coordination_task_expired", "deadline_passed")

        for task in self.tasks:
            if task.status != "queued":
                continue
            if step > task.deadline:
                task.status = "expired"
                self._record(task, step, "coordination_task_expired", "deadline_passed_in_queue")
                continue
            self._try_assign(task, step)

        loads = {resource_id: self._load(resource_id) for resource_id in self.resource_ids}
        self.max_resource_load = max(self.max_resource_load, max(loads.values(), default=0))
        for resource_id, load in loads.items():
            if load > self.capacity_per_resource:
                self.capacity_violation_count += 1
                self._record(None, step, "capacity_violation", f"{resource_id}:{load}", resource_id)

    def metrics(self) -> dict[str, int | float | None]:
        created = len(self.tasks)
        completed = sum(task.status == "completed" for task in self.tasks)
        assigned = [task for task in self.tasks if task.assigned_at is not None]
        pending = sum(task.status in {"queued", "assigned"} for task in self.tasks)
        assignment_delays = [task.assigned_at - task.created_at for task in assigned if task.assigned_at is not None]
        return {
            "coordination_tasks_created": created,
            "coordination_tasks_completed": completed,
            "coordination_tasks_expired": sum(task.status == "expired" for task in self.tasks),
            "coordination_tasks_dropped": sum(task.status == "dropped" for task in self.tasks),
            "coordination_tasks_pending": pending,
            "coordination_task_completion_rate": completed / created if created else None,
            "assignment_conflicts": self.conflict_count,
            "assignment_conflict_rate_per_100_tasks": 100.0 * self.conflict_count / created if created else None,
            "capacity_violations": self.capacity_violation_count,
            "max_resource_load": self.max_resource_load,
            "mean_assignment_wait_steps": (
                sum(assignment_delays) / len(assignment_delays) if assignment_delays else None
            ),
        }

    def _try_assign(self, task: CoordinationTask, step: int) -> bool:
        if self.mode == "centralized":
            available = [
                resource_id
                for resource_id in self.resource_ids
                if self._load(resource_id) < self.capacity_per_resource
            ]
            if not available:
                return False
            resource_id = min(available, key=lambda candidate: (self._load(candidate), candidate))
        else:
            proposals = self._decentralized_proposals(task)
            if not proposals:
                return False
            candidates = sorted(set(proposals))
            if len(candidates) > 1:
                self.conflict_count += 1
                self._record(
                    task,
                    step,
                    "assignment_conflict",
                    "proposals=" + ",".join(candidates),
                )
            # All peers use the same deterministic tie-break after comparing proposals.
            resource_id = candidates[0]

        if self._load(resource_id) >= self.capacity_per_resource:
            return False
        task.resource_id = resource_id
        task.assigned_at = step
        task.completes_at = step + self.task_duration_steps
        task.status = "assigned"
        self._record(task, step, "coordination_task_assigned", resource_id, resource_id)
        self._record(task, step, "coordination_task_started", "abstract_review", resource_id)
        return True

    def _decentralized_proposals(self, task: CoordinationTask) -> list[str]:
        proposals: list[str] = []
        for proposer in self.resource_ids:
            digest = hashlib.blake2b(
                f"{task.task_id}:{proposer}".encode("utf-8"),
                digest_size=4,
            ).digest()
            start = int.from_bytes(digest, "big") % len(self.resource_ids)
            preference_order = self.resource_ids[start:] + self.resource_ids[:start]
            candidate = next(
                (
                    resource_id
                    for resource_id in preference_order
                    if self._load(resource_id) < self.capacity_per_resource
                ),
                None,
            )
            if candidate is not None:
                proposals.append(candidate)
        return proposals

    def _load(self, resource_id: str) -> int:
        return sum(task.status == "assigned" and task.resource_id == resource_id for task in self.tasks)

    def _record(
        self,
        task: CoordinationTask | None,
        step: int,
        event_type: str,
        details: str,
        resource_id: str = "",
    ) -> None:
        self.events.append(
            {
                "step": step,
                "event_type": event_type,
                "message_id": "",
                "sender_id": "",
                "recipient_id": "",
                "entity_id": task.entity_id if task else "",
                "details": details,
                "copy_index": 0,
                "task_id": task.task_id if task else "",
                "task_type": "abstract-review" if task else "",
                "deadline": task.deadline if task else "",
                "priority": "",
                "processing_cost": "",
                "remaining_cost": "",
                "information_time": "",
                "resource_id": resource_id or (task.resource_id if task else ""),
            }
        )
