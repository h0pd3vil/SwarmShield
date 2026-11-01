from dataclasses import replace
import unittest

from swarmshield.config import SimulationConfig
from swarmshield.runner import run_simulation, write_events
from tempfile import TemporaryDirectory
from pathlib import Path


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = SimulationConfig(
            seed=17,
            steps=6,
            world_width=20,
            world_height=20,
            observer_count=2,
            entity_count=3,
            detection_range=100,
            detection_probability=1.0,
            position_noise_std=0.0,
            max_track_age_steps=6,
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            processing_capacity_per_step=1000,
            min_task_deadline_steps=0,
            max_task_deadline_steps=0,
            max_task_processing_cost=1,
            coordination_task_duration_steps=1,
        )

    def test_independent_run_has_no_peer_messages(self):
        summary, events = run_simulation(self.config, "independent")
        self.assertEqual(summary["metrics"]["messages_sent"], 0)
        self.assertEqual(summary["metrics"]["any_agent_awareness_coverage"], 1.0)
        self.assertEqual(len([e for e in events if e["event_type"] == "simulation_snapshot"]), 6)

    def test_same_seed_and_policy_reproduce_engine_output(self):
        first_summary, first_events = run_simulation(self.config, "cooperative", "edf")
        second_summary, second_events = run_simulation(self.config, "cooperative", "edf")
        first_summary["metrics"].pop("wall_clock_runtime_seconds")
        second_summary["metrics"].pop("wall_clock_runtime_seconds")
        self.assertEqual(first_summary, second_summary)
        self.assertEqual(first_events, second_events)

    def test_event_csv_export(self):
        _, events = run_simulation(self.config, "independent")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "events.csv"
            write_events(path, events)
            self.assertTrue(path.exists())
            self.assertIn("simulation_snapshot", path.read_text(encoding="utf-8"))

    def test_coordinator_mode_can_be_selected(self):
        decentralized = replace(self.config, coordination_mode="decentralized")
        summary, _ = run_simulation(decentralized, "independent")
        self.assertGreater(summary["metrics"]["coordination_tasks_created"], 0)
        self.assertEqual(summary["metrics"]["capacity_violations"], 0)


if __name__ == "__main__":
    unittest.main()
