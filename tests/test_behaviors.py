import unittest

from swarmshield.config import SimulationConfig
from swarmshield.geometry import PolygonFeature, WorldGeometry
from swarmshield.session import SimulationSession
from swarmshield.tasks import parse_task_definitions


class AutonomousBehaviorTests(unittest.TestCase):
    @staticmethod
    def raw_task(task_id="survey-a"):
        return {
            "task_id": task_id,
            "task_type": "reconnaissance",
            "location": [18, 10],
            "region": [[16, 8], [20, 8], [20, 12], [16, 12]],
            "prerequisites": [],
            "priority": 2,
            "deadline_step": 20,
            "estimated_duration_steps": 2,
            "required_capabilities": ["visual_sensor"],
            "completion_criteria": {"kind": "observe_region", "minimum_observations": 1},
        }

    @classmethod
    def make_session(cls, task=True, observer_count=1, **changes):
        values = dict(
            seed=7,
            steps=20,
            world_width=20,
            world_height=20,
            observer_count=observer_count,
            entity_count=1,
            detection_range=10,
            detection_probability=1.0,
            position_noise_std=0,
            processing_capacity_per_step=100,
        )
        values.update(changes)
        config = SimulationConfig(**values)
        definitions = ()
        if task:
            definitions = parse_task_definitions(
                [task if isinstance(task, dict) else cls.raw_task()],
                config.world_width,
                config.world_height,
                config.steps,
            )
        return SimulationSession(config, "cooperative", mission_tasks=definitions)

    def test_assigned_task_dispatches_once_and_autonomously_completes_from_sensing(self):
        session = self.make_session()
        session.world._entities[0].x = 18
        session.world._entities[0].y = 10
        session.world._entities[0].vx = 0
        session.world._entities[0].vy = 0
        session.assign_pending_mission_tasks()

        first = session.run_autonomous_behaviors()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["status"], "navigating")
        self.assertEqual(session.mission_tasks["survey-a"].status, "navigating")
        self.assertEqual(session.run_autonomous_behaviors(), [], "the same route must not be dispatched repeatedly")

        session.advance_tick()
        task = session.mission_tasks["survey-a"]
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.completed_at, 1)
        self.assertEqual(task.result["criterion"], "observe_region")
        self.assertTrue(any(event["event_type"] == "mission_task_completed" for event in task.event_history))

    def test_unavailable_owner_is_reassigned_to_a_valid_free_agent(self):
        session = self.make_session(observer_count=2)
        task = session.mission_tasks["survey-a"]
        session.task_state_machine.transition(task, "assigned", 0, agent_id="agent-001")
        session.agents["agent-001"].vehicle.current_task_id = "survey-a"
        session.agents["agent-001"].vehicle.status = "unavailable"

        session.run_autonomous_behaviors()

        self.assertEqual(task.assigned_agent_id, "agent-002")
        self.assertEqual(task.status, "navigating")
        self.assertEqual(session.agents["agent-002"].vehicle.current_task_id, "survey-a")
        self.assertIsNone(session.agents["agent-001"].vehicle.current_task_id)
        event_types = [event["event_type"] for event in session.sorted_events()]
        self.assertIn("mission_task_reassigned", event_types)
        self.assertIn("mission_task_navigating", event_types)

    def test_free_low_battery_uav_returns_to_a_configured_safe_area(self):
        geometry = WorldGeometry(safe_areas=(PolygonFeature(
            "recovery-zone", "recovery", ((2, 2), (8, 2), (8, 8), (2, 8)),
        ),))
        session = self.make_session(task=False, geometry=geometry)
        agent = session.agents["agent-001"]
        agent.vehicle.battery_remaining = 150

        outcomes = session.run_autonomous_behaviors()

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["status"], "navigating")
        self.assertIsNotNone(agent.recovery_target)
        self.assertTrue(session.world.is_in_safe_area(agent.recovery_target))
        self.assertTrue(any(event["event_type"] == "uav_recovery_started" for event in session.observation_events))


if __name__ == "__main__":
    unittest.main()
