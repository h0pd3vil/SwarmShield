import unittest

from swarmshield.config import SimulationConfig
from swarmshield.observations import Observation
from swarmshield.session import SimulationSession
from swarmshield.task_lifecycle import MissionTaskStateMachine
from swarmshield.tasks import parse_task_definitions


def _task(deadline_step=5):
	return {
		"task_id": "survey-a",
		"task_type": "coverage",
		"location": [5, 5],
		"region": [[2, 2], [8, 2], [8, 8], [2, 8]],
		"prerequisites": [],
		"priority": 1,
		"deadline_step": deadline_step,
		"estimated_duration_steps": 1,
		"required_capabilities": ["visual_sensor"],
		"completion_criteria": {"kind": "cover_region", "coverage_fraction": 0.2},
	}


class MissionMetricsTests(unittest.TestCase):
	@staticmethod
	def make_session(deadline_step=5, observer_count=2):
		config = SimulationConfig(
			seed=17,
			steps=8,
			world_width=20,
			world_height=20,
			observer_count=observer_count,
			entity_count=2,
			detection_range=8,
			field_of_view_degrees=360,
			require_line_of_sight=False,
			position_noise_std=0,
		)
		definitions = parse_task_definitions([_task(deadline_step)], 20, 20, config.steps)
		return SimulationSession(config, "cooperative", mission_tasks=definitions)

	def test_deadline_miss_metrics_use_inclusive_task_deadlines(self):
		session = self.make_session(deadline_step=1)
		at_deadline = session._mission_metrics(1)
		self.assertEqual(at_deadline["mission_deadline_eligible_tasks"], 0)
		self.assertIsNone(at_deadline["mission_task_deadline_miss_rate"])
		after_deadline = session._mission_metrics(2)
		self.assertEqual(after_deadline["mission_deadline_eligible_tasks"], 1)
		self.assertEqual(after_deadline["mission_task_deadline_misses"], 1)
		self.assertEqual(after_deadline["mission_task_deadline_miss_rate"], 1.0)

	def test_area_coverage_counts_actual_sensor_footprint_and_physical_resources(self):
		session = self.make_session(observer_count=1)
		agent = session.agents["agent-001"]
		agent.vehicle.x = 5.0
		agent.vehicle.y = 5.0
		agent.vehicle.distance_travelled = 8.5
		agent.vehicle.battery_remaining = agent.vehicle.motion_config.battery_capacity - 8.5
		session._record_mission_area_pose(agent, (0, 5.0, 5.0, 0.0))
		metrics = session.live_metrics()
		self.assertGreater(metrics["mission_area_sample_points"], 0)
		self.assertEqual(metrics["mission_area_covered_sample_points"], metrics["mission_area_sample_points"])
		self.assertEqual(metrics["mission_area_coverage_fraction"], 1.0)
		self.assertEqual(metrics["total_uav_distance_travelled"], 8.5)
		self.assertEqual(metrics["uav_energy_consumed"], 8.5)

	def test_shared_application_delay_and_overlapping_reports_are_actual_events(self):
		session = self.make_session(observer_count=2)
		session.step = 5
		session._apply_report(
			session.agents["agent-001"],
			Observation("entity-001", 4.0, 4.0, 2, "agent-002"),
		)
		session.observation_events.extend([
			{"event_type": "observation_created", "entity_id": "entity-001", "step": 4, "sender_id": "agent-001"},
			{"event_type": "observation_created", "entity_id": "entity-001", "step": 4, "sender_id": "agent-002"},
			{"event_type": "observation_created", "entity_id": "entity-002", "step": 4, "sender_id": "agent-001"},
		])
		metrics = session.live_metrics()
		self.assertEqual(metrics["shared_track_applications"], 1)
		self.assertEqual(metrics["mean_observation_to_shared_application_delay_steps"], 3.0)
		self.assertEqual(metrics["observation_reports_total"], 3)
		self.assertEqual(metrics["overlapping_observation_reports"], 1)
		self.assertAlmostEqual(metrics["overlapping_observation_report_rate"], 1 / 3)

	def test_completed_mission_metrics_use_state_machine_evidence(self):
		session = self.make_session(observer_count=1)
		task = session.mission_tasks["survey-a"]
		machine = MissionTaskStateMachine()
		machine.transition(task, "assigned", 0, agent_id="agent-001")
		machine.transition(task, "navigating", 0, agent_id="agent-001")
		machine.transition(task, "executing", 0, agent_id="agent-001")
		machine.transition(
			task, "completed", 3, agent_id="agent-001",
			evidence={"criterion": "cover_region", "satisfied": True, "coverage_fraction": 0.75},
		)
		metrics = session._mission_metrics(4)
		self.assertEqual(metrics["mission_tasks_completed"], 1)
		self.assertEqual(metrics["mission_task_completion_rate"], 1.0)
		self.assertEqual(metrics["mission_completion_time_steps"], 3)
		self.assertEqual(metrics["mission_mean_task_completion_time_steps"], 3.0)
		self.assertEqual(metrics["mission_task_assignment_events"], 1)
		self.assertEqual(metrics["mission_assignment_actions_per_task"], 1.0)

	def test_legacy_runs_without_spatial_tasks_keep_their_metric_schema(self):
		session = SimulationSession(SimulationConfig(steps=1), "independent")
		metrics = session.finalize()["metrics"]
		self.assertNotIn("mission_task_count", metrics)
		self.assertNotIn("mission_area_coverage_fraction", metrics)


if __name__ == "__main__":
	unittest.main()
