import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace
from unittest.mock import patch

from swarmshield.missions import load_mission, save_run_artifacts
from swarmshield.session import SimulationSession
from swarmshield.tasks import parse_task_definitions


class MissionCoordinationTests(unittest.TestCase):
    @staticmethod
    def run_mission(seed=42):
        config, mission = load_mission("shared_awareness", seed)
        definitions = parse_task_definitions(
            mission["tasks"], config.world_width, config.world_height, config.steps,
        )
        session = SimulationSession(config, "cooperative", mission_tasks=definitions)
        session.assign_pending_mission_tasks()
        session.run_autonomous_behaviors()
        while not session.finished:
            session.advance_tick()
        return session, mission

    def test_four_uavs_complete_distinct_spatial_tasks_and_save_actual_events(self):
        session, mission = self.run_mission(42)
        tasks = tuple(session.mission_tasks.values())
        self.assertEqual(len(tasks), 4)
        self.assertTrue(all(task.status == "completed" for task in tasks))
        self.assertEqual(len({task.assigned_agent_id for task in tasks}), 4)
        self.assertEqual(set(task.assigned_agent_id for task in tasks), set(session.agents))
        self.assertTrue(all(session.agents[task.assigned_agent_id].vehicle.distance_travelled > 20 for task in tasks))
        self.assertGreater(session.network.sent_originals, 0)
        metrics = session.summary["metrics"]
        self.assertEqual(metrics["mission_task_count"], 4)
        self.assertEqual(metrics["mission_tasks_completed"], 4)
        self.assertEqual(metrics["mission_task_completion_rate"], 1.0)
        self.assertEqual(metrics["mission_task_deadline_miss_rate"], 0.0)
        self.assertIsNotNone(metrics["mission_completion_time_steps"])
        self.assertGreater(metrics["mission_area_covered_sample_points"], 0)
        self.assertGreaterEqual(metrics["mission_area_coverage_fraction"], 0.6)
        self.assertGreater(metrics["total_uav_distance_travelled"], 0.0)
        self.assertGreater(metrics["uav_energy_consumed"], 0.0)

        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            artifact_path = Path(save_run_artifacts(session, mission))
            with (artifact_path / "events.csv").open(newline="", encoding="utf-8") as file:
                events = list(csv.DictReader(file))
            completed = [event for event in events if event["event_type"] == "mission_task_completed"]
            assigned = [event for event in events if event["event_type"] == "mission_task_assigned"]
            moved = [event for event in events if event["event_type"] in {"uav_moved", "uav_arrived"}]
            self.assertEqual(len(assigned), 4)
            self.assertEqual(len(completed), 4)
            self.assertTrue(moved)
            for event in completed:
                evidence = json.loads(event["details"])["evidence"]
                self.assertEqual(evidence["criterion"], "cover_region")
                self.assertGreaterEqual(evidence["coverage_fraction"], 0.6)

    def test_same_seed_replays_identical_task_and_engine_event_histories(self):
        first, _ = self.run_mission(42)
        second, _ = self.run_mission(42)
        self.assertEqual(first.sorted_events(), second.sorted_events())
        self.assertEqual(
            {task_id: task.to_dict() for task_id, task in first.mission_tasks.items()},
            {task_id: task.to_dict() for task_id, task in second.mission_tasks.items()},
        )
        self.assertEqual(
            {agent_id: agent.vehicle.distance_travelled for agent_id, agent in first.agents.items()},
            {agent_id: agent.vehicle.distance_travelled for agent_id, agent in second.agents.items()},
        )

    def test_partition_defers_unavailable_owner_reassignment_until_communication_returns(self):
        config, mission = load_mission("shared_awareness", 11)
        config = replace(config, partition_enabled=True)
        definition = parse_task_definitions(
            mission["tasks"][:1], config.world_width, config.world_height, config.steps,
        )
        definition = (replace(definition[0], deadline_step=config.steps),)
        session = SimulationSession(config, "cooperative", mission_tasks=definition)
        task = session.mission_tasks["survey-west"]
        session.task_state_machine.transition(task, "assigned", 0, agent_id="agent-001")
        session.agents["agent-001"].vehicle.current_task_id = task.definition.task_id
        session.agents["agent-001"].vehicle.status = "unavailable"

        session.step = 40
        self.assertEqual(session.network.communication_state(40), "partitioned")
        session.run_autonomous_behaviors()
        task_events = session.task_state_machine.advance(
            session.mission_tasks, session.agents, session.world, 40, communication_available=False,
        )
        self.assertEqual(task.assigned_agent_id, "agent-001")
        self.assertEqual(task.status, "assigned")
        self.assertEqual(task_events, [])

        session.step = 66
        self.assertEqual(session.network.communication_state(66), "available")
        session.run_autonomous_behaviors()
        self.assertEqual(task.assigned_agent_id, "agent-003")
        self.assertEqual(task.status, "navigating")
        reassignments = [event for event in session.sorted_events() if event["event_type"] == "mission_task_reassigned"]
        self.assertEqual(len(reassignments), 1)
        self.assertEqual(reassignments[0]["step"], 66)


if __name__ == "__main__":
    unittest.main()
