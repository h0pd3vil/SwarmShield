import unittest

from swarmshield.metrics import nearest_rank_percentile, summarize_paired_differences


class MetricTests(unittest.TestCase):
    def test_nearest_rank_percentiles(self):
        values = [8, 1, 4, 2, 10]
        self.assertEqual(nearest_rank_percentile(values, 50), 4)
        self.assertEqual(nearest_rank_percentile(values, 95), 10)

    def test_empty_percentile_has_no_value(self):
        self.assertIsNone(nearest_rank_percentile([], 95))

    def test_percentile_range_is_validated(self):
        with self.assertRaises(ValueError):
            nearest_rank_percentile([1], 0)

    def test_paired_difference_interval_reports_sample_uncertainty(self):
        result = summarize_paired_differences([1.0, 2.0, 3.0])
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["mean_difference"], 2.0)
        self.assertLess(result["ci95_low"], 2.0)
        self.assertGreater(result["ci95_high"], 2.0)
        self.assertIn("Student-t", result["interval_method"])

    def test_single_paired_difference_has_no_interval(self):
        result = summarize_paired_differences([4.0])
        self.assertEqual(result["mean_difference"], 4.0)
        self.assertIsNone(result["ci95_low"])
        self.assertIsNone(result["ci95_high"])


if __name__ == "__main__":
    unittest.main()
