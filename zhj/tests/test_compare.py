import unittest

from memsched_exp.compare import compare_rows


def row(variant, pair_id, value, environment="same"):
    return {
        "variant": variant,
        "pair_id": pair_id,
        "scenario": "demo",
        "environment_hash": environment,
        "measurement_valid": True,
        "launch_latency_ms": value,
    }


class CompareTest(unittest.TestCase):
    def test_paired_statistics_and_improvement(self):
        value = compare_rows(
            [
                row("baseline", "p1", 100),
                row("candidate", "p1", 80),
                row("baseline", "p2", 120),
                row("candidate", "p2", 90),
            ],
            iterations=100,
            bootstrap_seed=1,
        )
        metric = next(item for item in value["metrics"] if item["metric"] == "launch_latency_ms")
        self.assertEqual(value["paired_runs"], 2)
        self.assertEqual(metric["baseline"]["median"], 110)
        self.assertAlmostEqual(metric["improvement_percent_from_means"], 22.7272727)

    def test_environment_mismatch_is_not_paired(self):
        value = compare_rows(
            [row("baseline", "p1", 100, "a"), row("candidate", "p1", 80, "b")],
            iterations=10,
        )
        self.assertFalse(value["valid"])
        self.assertEqual(value["skipped"]["environment_mismatch"], 1)


if __name__ == "__main__":
    unittest.main()
