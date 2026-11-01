import unittest

from swarmshield.coordination import CoordinationManager


class CoordinationTests(unittest.TestCase):
    def test_central_manager_enforces_capacity_and_releases_completed_work(self):
        manager = CoordinationManager(
            resource_ids=("agent-a", "agent-b"),
            mode="centralized",
            capacity_per_resource=1,
            task_duration_steps=2,
            task_deadline_steps=10,
            queue_capacity=10,
        )
        first = manager.request_review("entity-1", 1)
        second = manager.request_review("entity-2", 1)
        third = manager.request_review("entity-3", 1)
        self.assertEqual(first.status, "assigned")
        self.assertEqual(second.status, "assigned")
        self.assertEqual(third.status, "queued")
        manager.tick(3)
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        self.assertEqual(third.status, "assigned")
        self.assertEqual(manager.capacity_violation_count, 0)

    def test_decentralized_mode_logs_proposal_conflicts(self):
        manager = CoordinationManager(
            resource_ids=("agent-a", "agent-b", "agent-c", "agent-d"),
            mode="decentralized",
            capacity_per_resource=20,
            task_duration_steps=3,
            task_deadline_steps=10,
            queue_capacity=100,
        )
        for index in range(20):
            manager.request_review(f"entity-{index}", 1)
        self.assertGreater(manager.conflict_count, 0)
        self.assertEqual(manager.capacity_violation_count, 0)

    def test_duplicate_entity_does_not_create_another_coordination_task(self):
        manager = CoordinationManager(
            resource_ids=("agent-a",),
            mode="centralized",
            capacity_per_resource=2,
            task_duration_steps=1,
            task_deadline_steps=3,
            queue_capacity=10,
        )
        self.assertIsNotNone(manager.request_review("entity-1", 1))
        self.assertIsNone(manager.request_review("entity-1", 2))
        self.assertEqual(len(manager.tasks), 1)


if __name__ == "__main__":
    unittest.main()
