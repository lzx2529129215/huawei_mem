#!/usr/bin/env python3
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(ROOT.parent))

from parse_kswapd_trace import convert


class ParserTest(unittest.TestCase):
    def read_rows(self, path):
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_normal_request_and_efficiency(self):
        with tempfile.TemporaryDirectory() as directory:
            incomplete, events = convert(FIXTURES / "normal.trace", Path(directory))
            self.assertEqual((incomplete, events), (0, 3))
            request = self.read_rows(Path(directory) / "kswapd_requests.csv")[0]
            self.assertEqual(request["complete"], "1")
            self.assertEqual(request["exit_reason"], "BALANCED")
            self.assertEqual(float(request["overall_efficiency"]), 0.5)

    def test_restart_and_same_priority_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            incomplete, _ = convert(FIXTURES / "restart_same_priority.trace", Path(directory))
            self.assertEqual(incomplete, 0)
            rounds = self.read_rows(Path(directory) / "kswapd_rounds.csv")
            self.assertEqual([row["round_seq"] for row in rounds], ["0", "1"])
            self.assertEqual([row["pass_seq"] for row in rounds], ["0", "1"])
            self.assertEqual([row["priority"] for row in rounds], ["12", "12"])

    def test_incomplete_is_excluded_from_efficiency(self):
        with tempfile.TemporaryDirectory() as directory:
            incomplete, _ = convert(FIXTURES / "incomplete.trace", Path(directory))
            self.assertEqual(incomplete, 1)
            request = self.read_rows(Path(directory) / "kswapd_requests.csv")[0]
            self.assertEqual(request["complete"], "0")
            self.assertEqual(request["overall_efficiency"], "")
            self.assertEqual(self.read_rows(Path(directory) / "kswapd_efficiency.csv"), [])

    def test_zero_round_and_zero_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            incomplete, _ = convert(FIXTURES / "zero_round.trace", Path(directory))
            self.assertEqual(incomplete, 0)
            request = self.read_rows(Path(directory) / "kswapd_requests.csv")[0]
            self.assertEqual(request["round_count"], "0")
            self.assertEqual(request["overall_efficiency"], "")
            self.assertEqual(self.read_rows(Path(directory) / "kswapd_efficiency.csv"), [])

    def test_missing_begin_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            incomplete, _ = convert(FIXTURES / "missing_begin.trace", Path(directory))
            self.assertEqual(incomplete, 1)
            request = self.read_rows(Path(directory) / "kswapd_requests.csv")[0]
            self.assertIn("missing_begin", request["completeness_errors"])

    def test_totals_and_validation_flags_are_incomplete(self):
        for fixture in ("bad_totals.trace", "bad_validation.trace"):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as directory:
                incomplete, _ = convert(FIXTURES / fixture, Path(directory))
                self.assertEqual(incomplete, 1)
                request = self.read_rows(Path(directory) / "kswapd_requests.csv")[0]
                self.assertEqual(request["complete"], "0")


if __name__ == "__main__":
    unittest.main()
