import random
import unittest

from swarmshield.scheduler import DecisionScheduler


def make_scheduler(policy="fixed-priority", capacity=1, queue_capacity=10, deadline=5):
    return DecisionScheduler(
        rng=random.Random(3),
        policy=policy,
        processing_capacity_per_step=capacity,
        queue_capacity=queue_capacity,
        min_deadline_steps=deadline,
        max_deadline_steps=deadline,
        max_processing_cost=1,
        max_priority=3,
    )


class SchedulerTests(unittest.TestCase):
    def test_fixed_priority_selects_highest_priority_first(self):
        scheduler = make_scheduler("fixed-priority")
        scheduler.submit("low", "decision", 1, 1)
        scheduler.submit("high", "decision", 1, 1)
        low, high = scheduler.tasks
        low.priority = 1
        high.priority = 3
        low.processing_cost = low.remaining_cost = 2
        high.processing_cost = high.remaining_cost = 2
        scheduler.tick(1)
        self.assertEqual(high.started_at, 1)
        self.assertIsNone(low.started_at)

    def test_edf_selects_earliest_deadline_first(self):
        scheduler = make_scheduler("edf")
        scheduler.submit("later", "decision", 1, 1)
        scheduler.submit("earlier", "decision", 1, 1)
        later, earlier = scheduler.tasks
        later.deadline = 8
        earlier.deadline = 4
        later.processing_cost = later.remaining_cost = 2
        earlier.processing_cost = earlier.remaining_cost = 2
        scheduler.tick(1)
        self.assertEqual(earlier.started_at, 1)
        self.assertIsNone(later.started_at)

    def test_overload_drops_new_task_explicitly(self):
        scheduler = make_scheduler(queue_capacity=1)
        self.assertTrue(scheduler.submit("one", "decision", 1, 1))
        self.assertFalse(scheduler.submit("two", "decision", 1, 1))
        self.assertEqual(scheduler.tasks[1].status, "dropped")
        self.assertTrue(any(event["event_type"] == "task_dropped" for event in scheduler.events))

    def test_task_expires_after_its_deadline(self):
        scheduler = make_scheduler(capacity=1, deadline=1)
        scheduler.submit("slow", "decision", 1, 1)
        task = scheduler.tasks[0]
        task.processing_cost = task.remaining_cost = 4
        scheduler.tick(1)
        scheduler.tick(2)
        scheduler.tick(3)
        self.assertEqual(task.status, "expired")

    def test_future_deadline_task_is_pending_at_horizon(self):
        scheduler = make_scheduler(capacity=1, deadline=5)
        scheduler.submit("future", "decision", 1, 1)
        task = scheduler.tasks[0]
        task.processing_cost = task.remaining_cost = 4
        scheduler.tick(1)
        scheduler.record_pending(2)
        self.assertEqual(task.status, "pending_at_horizon")


if __name__ == "__main__":
    unittest.main()
