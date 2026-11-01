import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.run_batch import run_batch


class BatchTests(unittest.TestCase):
    def test_matched_batch_writes_one_row_per_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "seed": 5,
                        "world": {"steps": 3, "width": 20, "height": 20},
                        "scenario": {"observer_count": 1, "entity_count": 1},
                        "observation": {"range": 100, "detection_probability": 1.0},
                    }
                ),
                encoding="utf-8",
            )
            output_path = root / "results" / "summary.csv"
            rows = run_batch(
                config_path=config_path,
                seed_count=2,
                start_seed=9,
                modes=["independent"],
                policies=["fixed-priority", "edf"],
                output_path=output_path,
            )
            self.assertEqual(len(rows), 4)
            with output_path.open(newline="", encoding="utf-8") as csv_file:
                saved_rows = list(csv.DictReader(csv_file))
            self.assertEqual(len(saved_rows), 4)
            self.assertEqual({row["seed"] for row in saved_rows}, {"9", "10"})
            self.assertIn("deadline_miss_rate", saved_rows[0])


if __name__ == "__main__":
    unittest.main()
