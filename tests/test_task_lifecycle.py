import unittest

from swarmshield.config import SimulationConfig
from swarmshield.observations import Observation
from swarmshield.session import SimulationSession
from swarmshield.tasks import MissionTask, parse_task_definitions
from swarmshield.task_lifecycle import MissionTaskStateMachine


class MissionTaskLifecycleTests(unittest.TestCase):
    @staticmethod
    def raw_task(task_type="reconnaissance", criteria=None, **overrides):
        by_type = {
            "reconnaissance": {"kind": "observe_region", "minimum_observations": 1},
            "search": {"kind": "observe_entity", "entity_id": "entity-001"},
            "confirmation": {"kind": "confirm_entity", "entity_id": "entity-001"},
            "coverage": {"kind": "cover_region", "coverage_fraction": 0.2},
            "return_to_recovery": {"kind": "arrive", "arrival_radius": 1.0},
        }
        value = {
            "task_id": "task-a",
            "task_type": task_type,
            "location": [5, 5],
            "region": [[2, 2], [8, 2], [8, 8], [2, 8]],
            "prerequisites": [],
            "priority": 2,
            "deadline_step": 20,
            "estimated_duration_steps": 2,
            "required_capabilities": ["visual_sensor"],
            "completion_criteria": criteria or by_type[task_type],
        }
        if task_type == "return_to_recovery":
            value["region"] = None
        value.update(overrides)
        return value

    @classmethod
    def make_session(cls, raw=None, observer_count=2, **config_changes):
        config_values = dict(
            steps=30,
            world_width=20,
            world_height=20,
            observer_count=observer_count,
            entity_count=1,
            detection_range=8,
            position_noise_std=0,
        )
        config_values.update(config_changes)
        config = SimulationConfig(**config_values)
        definition = parse_task_definitions(
            [raw or cls.raw_task()], config.world_width, config.world_height, config.steps,
        )[0]
        session = SimulationSession(config, "cooperative", mission_tasks=(definition,))
        return session, session.mission_tasks[definition.task_id]

    @staticmethod
    def assign_for_lifecycle(session, task, agent_id="agent-001"):
        session.task_state_machine.transition(task, "assigned", 0, agent_id=agent_id)
        session.agents[agent_id].vehicle.current_task_id = task.definition.task_id

    def test_transition_graph_rejects_skips_and_completion_without_evidence(self):
        session, task = self.make_session()
        machine = MissionTaskStateMachine()
        with self.assertRaisesRegex(ValueError, "invalid mission task transition"):
            machine.transition(task, "completed", 0, evidence={"criterion": "observe_region", "satisfied": True})

        self.assign_for_lifecycle(session, task)
        machine.transition(task, "navigating", 0, agent_id="agent-001")
        machine.transition(task, "executing", 0, agent_id="agent-001")
        with self.assertRaisesRegex(ValueError, "requires satisfied engine evidence"):
            machine.transition(task, "completed", 1)
        with self.assertRaisesRegex(ValueError, "requires satisfied engine evidence"):
            machine.transition(task, "completed", 1, evidence={"criterion": "observe_region", "satisfied": False})
        self.assertEqual(task.status, "executing")

    def test_estimated_duration_never_completes_a_task(self):
        session, task = self.make_session()
        self.assign_for_lifecycle(session, task)
        machine = session.task_state_machine
        machine.transition(task, "navigating", 1, agent_id="agent-001")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 18, 18
        agent.vehicle.status = "navigating"
        agent.vehicle.destination = (19, 18)
        for step in range(2, task.definition.estimated_duration_steps + 5):
            machine.advance(session.mission_tasks, session.agents, session.world, step)
        self.assertEqual(task.status, "navigating")
        self.assertIsNone(task.completed_at)

    def test_reconnaissance_completes_from_new_local_observation_in_region(self):
        session, task = self.make_session(observer_count=1)
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        agent.vehicle.status = "available"
        agent.pose_history.append((1, 5, 5, 0))
        events = session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "executing")
        self.assertEqual(task.started_at, 1)
        self.assertEqual([event["event_type"] for event in events], ["mission_task_navigating", "mission_task_started"])

        agent.observe_locally(Observation("entity-001", 6, 5, 1, "agent-001"))
        events = session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.completed_at, 2)
        self.assertEqual(events[-1]["event_type"], "mission_task_completed")
        self.assertEqual(task.result["criterion"], "observe_region")

    def test_protection_monitoring_requires_two_local_observations_inside_configured_radius(self):
        criteria = {
            "kind": "monitor_entity",
            "entity_id": "entity-001",
            "radius": 3.0,
            "minimum_observations": 2,
        }
        session, task = self.make_session(
            self.raw_task("search", criteria=criteria), observer_count=1,
        )
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        agent.vehicle.status = "available"
        agent.pose_history.append((1, 5, 5, 0))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)

        agent.observe_locally(Observation("entity-001", 7, 5, 1, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "executing")
        agent.pose_history.append((2, 5, 5, 0))
        agent.observe_locally(Observation("entity-001", 9, 5, 2, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(task.status, "executing", "an observation outside the perimeter must not count")

        agent.pose_history.append((3, 5, 5, 0))
        agent.observe_locally(Observation("entity-001", 7, 6, 3, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 3)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result["criterion"], "monitor_entity")
        self.assertEqual(task.result["monitoring_radius"], 3.0)

    def test_old_and_shared_observations_do_not_complete_assigned_uavs_survey(self):
        session, task = self.make_session(observer_count=2)
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        agent.observe_locally(Observation("entity-001", 5, 5, 0, "agent-001"))
        agent.pose_history.append((1, 5, 5, 0))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "executing")
        agent.apply_observation(Observation("entity-002", 5, 5, 2, "agent-002"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(task.status, "executing")
        agent.pose_history.append((3, 5, 5, 0))
        agent.observe_locally(Observation("entity-003", 5, 5, 3, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 3)
        self.assertEqual(task.status, "completed")

    def test_search_requires_distinct_local_observation_ticks(self):
        criteria = {"kind": "observe_entity", "entity_id": "entity-001", "minimum_observations": 2}
        session, task = self.make_session(self.raw_task("search", criteria=criteria), observer_count=1)
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        agent.observe_locally(Observation("entity-001", 5, 5, 1, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "executing")
        agent.observe_locally(Observation("entity-001", 5, 5, 2, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(task.status, "completed")

    def test_monitor_entity_criterion_validates_perimeter_radius(self):
        definition = parse_task_definitions(
            [self.raw_task(
                "search",
                criteria={
                    "kind": "monitor_entity",
                    "entity_id": "entity-001",
                    "radius": 4.5,
                },
            )],
            world_width=20,
            world_height=20,
            horizon_steps=30,
        )[0]
        self.assertEqual(definition.completion_criteria["radius"], 4.5)
        self.assertEqual(definition.completion_criteria["minimum_observations"], 2)
        with self.assertRaisesRegex(ValueError, "radius must be positive"):
            parse_task_definitions(
                [self.raw_task(
                    "search",
                    criteria={"kind": "monitor_entity", "entity_id": "entity-001", "radius": 0},
                )],
                world_width=20,
                world_height=20,
                horizon_steps=30,
            )

    def test_confirmation_defaults_to_two_independent_observers(self):
        definition = parse_task_definitions(
            [self.raw_task("confirmation")], 20, 20, 30,
        )[0]
        self.assertEqual(definition.completion_criteria["minimum_observations"], 2)
        session = SimulationSession(SimulationConfig(
            steps=30, world_width=20, world_height=20, observer_count=2, entity_count=1,
        ), "cooperative", mission_tasks=(definition,))
        task = session.mission_tasks["task-a"]
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        agent.observe_locally(Observation("entity-001", 5, 5, 1, "agent-001"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "executing")
        agent.apply_observation(Observation("entity-001", 5, 5, 1, "agent-002"))
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result["independent_observer_count"], 2)

    def test_coverage_uses_recorded_pose_sensor_footprint(self):
        session, task = self.make_session(
            self.raw_task("coverage", criteria={"kind": "cover_region", "coverage_fraction": 0.2}),
            observer_count=1,
            detection_range=3,
            field_of_view_degrees=360,
            require_line_of_sight=False,
        )
        self.assign_for_lifecycle(session, task)
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5, 5
        session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        agent.pose_history.append((1, 5, 5, 0))
        events = session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 1)
        self.assertEqual(task.status, "completed")
        self.assertGreaterEqual(task.result["coverage_fraction"], 0.2)
        self.assertEqual(events[-1]["event_type"], "mission_task_completed")

    def test_deadline_is_inclusive_then_expires_and_unavailable_agents_fail(self):
        session, task = self.make_session(self.raw_task(deadline_step=2), observer_count=1)
        self.assign_for_lifecycle(session, task)
        task.status = "assigned"
        events = session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 2)
        self.assertEqual(events, [])
        events = session.task_state_machine.advance(session.mission_tasks, session.agents, session.world, 3)
        self.assertEqual(task.status, "expired")
        self.assertEqual(events[0]["event_type"], "mission_task_expired")

        other, failed_task = self.make_session(observer_count=1)
        self.assign_for_lifecycle(other, failed_task)
        other.agents["agent-001"].vehicle.status = "unavailable"
        failed = other.task_state_machine.advance(other.mission_tasks, other.agents, other.world, 1)
        self.assertEqual(failed_task.status, "failed")
        self.assertEqual(failed[0]["event_type"], "mission_task_failed")

    def test_cancel_and_reassign_are_validated_and_record_both_transitions(self):
        session, task = self.make_session(observer_count=2)
        self.assign_for_lifecycle(session, task)
        events = session.reassign_mission_task("task-a", "agent-002")
        self.assertEqual([event["event_type"] for event in events], ["mission_task_reassigned", "mission_task_assigned"])
        self.assertEqual(task.assigned_agent_id, "agent-002")
        self.assertIsNone(session.agents["agent-001"].vehicle.current_task_id)
        self.assertEqual(session.agents["agent-002"].vehicle.current_task_id, "task-a")
        cancelled = session.cancel_mission_task("task-a")
        self.assertEqual(cancelled["event_type"], "mission_task_cancelled")
        self.assertEqual(task.status, "cancelled")
        self.assertIsNone(session.agents["agent-002"].vehicle.current_task_id)

    def test_session_routes_assigned_task_and_snapshots_execution_transition(self):
        raw = self.raw_task(
            region=[[16, 8], [20, 8], [20, 12], [16, 12]],
            location=[18, 10],
            completion_criteria={"kind": "observe_region", "minimum_observations": 99},
        )
        session, task = self.make_session(raw, observer_count=1)
        assignments = session.assign_pending_mission_tasks()
        self.assertEqual(len(assignments), 1)
        self.assertEqual(task.status, "assigned")

        outcome = session.assign_destination("agent-001", (18, 10), "task-a")
        self.assertEqual(outcome["status"], "navigating")
        session.advance_tick()
        snapshot = session.snapshot()
        self.assertEqual(snapshot["mission_tasks"][0]["status"], "executing")
        task_events = [event["event_type"] for event in session.sorted_events() if event.get("task_id") == "task-a"]
        self.assertIn("mission_task_assigned", task_events)
        self.assertIn("mission_task_navigating", task_events)
        self.assertIn("mission_task_started", task_events)


if __name__ == "__main__":
    unittest.main()
