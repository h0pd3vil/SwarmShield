import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from swarmshield.comparisons import load_saved_comparison, list_saved_comparisons, run_matched_comparison
from swarmshield.protocol import ProtocolServer


class MatchedComparisonTests(unittest.TestCase):
    def test_scheduler_comparison_pairs_identical_seeds_and_saves_source_runs(self):
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory) / "runs"):
            comparison = run_matched_comparison(
                "deadline_pressure", 15, 2, "scheduler", "cooperative", "fixed-priority"
            )

            self.assertEqual(comparison["design"], "matched_seed")
            self.assertEqual(comparison["seeds"], [15, 16])
            self.assertEqual(comparison["left_treatment"]["policy"], "fixed-priority")
            self.assertEqual(comparison["right_treatment"]["policy"], "edf")
            self.assertEqual(len(comparison["runs"]), 4)
            self.assertEqual(len(comparison["paired_results"]), 2)
            self.assertEqual(comparison["aggregates"]["deadline_miss_rate"]["n"], 2)
            self.assertEqual(comparison["aggregates"]["mission_task_completion_rate"]["n"], 2)
            self.assertIsNotNone(comparison["aggregates"]["mission_task_completion_rate"]["ci95_low"])
            self.assertIsNotNone(comparison["aggregates"]["mission_task_completion_rate"]["ci95_high"])

            for pair in comparison["paired_results"]:
                seed_runs = [row for row in comparison["runs"] if row["seed"] == pair["seed"]]
                self.assertEqual({row["mode"] for row in seed_runs}, {"cooperative"})
                self.assertEqual({row["scheduler_policy"] for row in seed_runs}, {"fixed-priority", "edf"})
                for run in seed_runs:
                    summary_path = Path(run["artifact_path"]) / "summary.json"
                    saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    self.assertEqual(run["mission_status"], saved_summary["game_result"]["mission"]["status"])
                    self.assertEqual(run["metrics"]["game_score"], saved_summary["game_result"]["score"]["total_score"])
                    self.assertEqual(run["metrics"]["mission_task_completion_rate"], saved_summary["metrics"]["mission_task_completion_rate"])
                    self.assertGreater(saved_summary["metrics"]["mission_task_count"], 0)
                    self.assertGreater(saved_summary["metrics"]["total_uav_distance_travelled"], 0)
                    manifest = json.loads((summary_path.parent / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual(manifest["comparison"]["comparison_id"], comparison["comparison_id"])

            stored = load_saved_comparison(comparison["comparison_id"])
            self.assertEqual(stored["comparison_id"], comparison["comparison_id"])
            self.assertEqual(list_saved_comparisons()[0]["comparison_id"], comparison["comparison_id"])

    def test_sharing_comparison_holds_scheduler_constant_for_each_seed(self):
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory) / "runs"):
            comparison = run_matched_comparison(
                "shared_awareness", 4, 2, "sharing", "cooperative", "edf"
            )
            self.assertEqual(comparison["left_treatment"]["mode"], "independent")
            self.assertEqual(comparison["right_treatment"]["mode"], "cooperative")
            for seed in comparison["seeds"]:
                pair = [row for row in comparison["runs"] if row["seed"] == seed]
                self.assertEqual({row["scheduler_policy"] for row in pair}, {"edf"})
                self.assertEqual({row["mode"] for row in pair}, {"independent", "cooperative"})

    def test_invalid_comparison_inputs_are_rejected_before_artifact_creation(self):
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory) / "runs"):
            with self.assertRaisesRegex(ValueError, "seed_count"):
                run_matched_comparison("shared_awareness", 42, 1, "scheduler", "cooperative", "edf")
            with self.assertRaisesRegex(ValueError, "dimension"):
                run_matched_comparison("shared_awareness", 42, 2, "random", "cooperative", "edf")
            self.assertFalse((Path(directory) / "runs").exists())

    def test_protocol_loads_saved_comparison_and_rejects_bad_pairing_request(self):
        server = ProtocolServer()
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory) / "runs"):
            bad = server.handle_line(json.dumps({
                "version": 1,
                "command": "run_matched_comparison",
                "payload": {"scenario": "shared_awareness", "seed_count": 1},
            }))
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["error"]["code"], "invalid_comparison")

            request = server.handle_line(json.dumps({
                "version": 1,
                "command": "run_matched_comparison",
                "payload": {
                    "scenario": "shared_awareness",
                    "start_seed": 2,
                    "seed_count": 2,
                    "dimension": "sharing",
                    "policy": "edf",
                },
            }))
            self.assertTrue(request["ok"])
            comparison_id = request["result"]["comparison_id"]
            listed = server.handle_line(json.dumps({"version": 1, "command": "list_saved_comparisons"}))
            self.assertEqual(listed["result"]["comparisons"][0]["comparison_id"], comparison_id)
            loaded = server.handle_line(json.dumps({
                "version": 1,
                "command": "load_saved_comparison",
                "payload": {"comparison_id": comparison_id},
            }))
            self.assertTrue(loaded["ok"])
            self.assertEqual(loaded["result"]["comparison"]["comparison_id"], comparison_id)


if __name__ == "__main__":
    unittest.main()
