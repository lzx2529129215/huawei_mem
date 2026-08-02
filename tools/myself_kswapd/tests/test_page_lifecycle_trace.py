import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT.parent
sys.path.insert(0, str(TOOLS))

from parse_page_lifecycle_trace import (  # noqa: E402
    Classification,
    parse_and_replay_text,
    parse_trace_text,
)


FIELDS = {
    "transition_seq": 1,
    "action": 1,
    "page_id": 10,
    "lifecycle_gen": 1,
    "order": 0,
    "nr_pages": 1,
    "page_type": 0,
    "from_state": 0,
    "to_state": 1,
    "lru_class": 0,
    "mode": 0,
    "memcg_id": 55,
    "nid": 0,
    "request_id": 0,
    "priority_seq": 0,
    "scan_seq": 0,
    "reclaim_source": 3,
    "reason": 0,
    "flags": 0,
}


def event_line(alias="myself_kswapd_page_lifecycle", **changes):
    fields = dict(FIELDS)
    fields.update(changes)
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"worker-7 [001] .... 1.000001: {alias}: {payload}"


class PageLifecycleParserReplayTest(unittest.TestCase):
    def replay(self, *lines):
        return parse_and_replay_text("\n".join(lines) + "\n")

    def test_real_and_legacy_event_names_are_exactly_recognized(self):
        text = "\n".join((
            event_line(),
            event_line("myself_kswapd:page_lifecycle", transition_seq=2,
                       page_id=11),
            event_line("myself_kswapd:myself_kswapd_page_lifecycle",
                       transition_seq=3, page_id=12),
            "myself_kswapd_page_lifecycle: " +
            event_line().split(": ", 1)[1].replace("transition_seq=1",
                                                     "transition_seq=4")
            .replace("page_id=10", "page_id=13"),
            "worker [0] .... 1.1: other_event: "
            "note=myself_kswapd_page_lifecycle:",
            "worker [0] .... 1.2: page_lifecycle_extra: page_id=99",
        ))
        parsed = parse_trace_text(text)
        self.assertFalse(parsed.issues)
        self.assertEqual([event.fields["page_id"] for event in parsed.events],
                         [10, 11, 12, 13])

    def test_inactive_active_inactive_and_terminal_replay(self):
        report = self.replay(
            event_line(action=1, from_state=0, to_state=1),
            event_line(transition_seq=2, action=2, from_state=1, to_state=2,
                       lru_class=1),
            event_line(transition_seq=3, action=3, from_state=2, to_state=1),
            event_line(transition_seq=4, action=4, from_state=1, to_state=3,
                       request_id=8, priority_seq=2, scan_seq=4,
                       reclaim_source=0, lru_class=0),
            event_line(transition_seq=5, action=6, from_state=3, to_state=4,
                       request_id=8, priority_seq=2, scan_seq=4,
                       reclaim_source=0, lru_class=4),
        )
        self.assertEqual(report.summary["invalid_transition"], 0)
        self.assertEqual(report.summary["unique_lifecycles"], 1)
        self.assertEqual(report.summary["terminal_entries"], 1)
        self.assertEqual(report.summary["per_event_count"]["ACTIVATE"], 1)
        self.assertEqual(report.summary["per_state_count"]["RECLAIMED"], 1)

    def test_isolate_putback_paths_preserve_reclaim_context(self):
        for initial, lru_class in ((1, 0), (2, 1)):
            with self.subTest(initial=initial):
                report = self.replay(
                    event_line(to_state=initial, lru_class=lru_class),
                    event_line(transition_seq=2, action=4,
                               from_state=initial, to_state=3,
                               request_id=7, priority_seq=3, scan_seq=5,
                               reclaim_source=0, lru_class=lru_class),
                    event_line(transition_seq=3, action=5, from_state=3,
                               to_state=initial, request_id=7,
                               priority_seq=3, scan_seq=5,
                               reclaim_source=0, lru_class=lru_class),
                )
                self.assertEqual(report.summary["invalid_transition"], 0)
                self.assertEqual(report.summary["active_entries_at_end"], 1)

    def test_late_discovery_is_not_an_invalid_transition(self):
        report = self.replay(
            event_line(action=4, from_state=0, to_state=3, flags=1,
                       request_id=3, priority_seq=1, scan_seq=1,
                       reclaim_source=1),
            event_line(transition_seq=2, action=5, from_state=3, to_state=1,
                       request_id=3, priority_seq=1, scan_seq=1,
                       reclaim_source=1),
        )
        self.assertEqual(report.summary["late_discovery"], 1)
        self.assertEqual(report.summary["invalid_transition"], 0)
        self.assertIn(Classification.LATE_DISCOVERY,
                      {item.classification for item in report.transitions})

    def test_invalid_putback_activate_and_duplicate_terminal_are_distinct(self):
        report = self.replay(
            event_line(to_state=1),
            event_line(transition_seq=2, action=5, from_state=1, to_state=1),
            event_line(transition_seq=3, action=2, from_state=1, to_state=2,
                       lru_class=1),
            event_line(transition_seq=4, action=2, from_state=2, to_state=2,
                       lru_class=1),
            event_line(transition_seq=5, action=7, from_state=2, to_state=5,
                       lru_class=4),
            event_line(transition_seq=6, action=7, from_state=5, to_state=5,
                       lru_class=4, flags=4),
        )
        self.assertEqual(report.summary["putback_without_isolate"], 1)
        self.assertGreaterEqual(report.summary["invalid_transition"], 2)
        self.assertEqual(report.summary["duplicate_terminal"], 1)

    def test_reclaimed_without_isolate_and_missing_isolate_are_reported(self):
        report = self.replay(
            event_line(to_state=1),
            event_line(transition_seq=2, action=6, from_state=1, to_state=4,
                       lru_class=4),
        )
        self.assertEqual(report.summary["reclaimed_without_isolate"], 1)
        self.assertEqual(report.summary["missing_isolate"], 1)

    def test_first_incompatible_event_is_trace_truncation_not_kernel_error(self):
        report = self.replay(
            event_line(action=5, from_state=3, to_state=1),
        )
        self.assertEqual(report.summary["trace_truncation"], 1)
        self.assertEqual(report.summary["invalid_transition"], 0)
        self.assertEqual(report.transitions[0].classification,
                         Classification.TRACE_TRUNCATION)

    def test_reuse_flag_and_mixed_dimensions_are_summarized(self):
        report = self.replay(
            event_line(page_id=1, lifecycle_gen=1, memcg_id=5, nid=0),
            event_line(transition_seq=2, page_id=1, lifecycle_gen=1,
                       action=7, from_state=1, to_state=5, lru_class=4,
                       memcg_id=5),
            event_line(transition_seq=3, page_id=2, lifecycle_gen=2,
                       memcg_id=6, nid=1, mode=0, page_type=1,
                       lru_class=2, flags=16),
            event_line(transition_seq=4, page_id=3, lifecycle_gen=1,
                       memcg_id=0, nid=2, mode=1, page_type=1,
                       lru_class=2),
        )
        summary = report.summary
        self.assertEqual(summary["reuse_detected"], 1)
        self.assertEqual(summary["unique_lifecycles"], 3)
        self.assertEqual(summary["per_memcg_count"], {"0": 1, "5": 2, "6": 1})
        self.assertEqual(summary["per_nid_count"], {"0": 2, "1": 1, "2": 1})
        self.assertEqual(summary["per_mode_count"], {"GLOBAL": 1, "MEMCG": 3})

    def test_missing_fields_and_bad_request_hierarchy_are_parse_issues(self):
        missing = event_line().replace(" nr_pages=1", "")
        bad_ids = event_line(transition_seq=2, request_id=9,
                             priority_seq=0, scan_seq=0,
                             reclaim_source=0)
        parsed = parse_trace_text(missing + "\n" + bad_ids + "\n")
        self.assertEqual(len(parsed.events), 0)
        self.assertGreaterEqual(len(parsed.issues), 2)

    def test_cli_emits_json_and_csv_transitions(self):
        trace = "\n".join((
            event_line(),
            event_line(transition_seq=2, action=7, from_state=1,
                       to_state=5, lru_class=4),
        )) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "input.trace"
            csv_path = Path(directory) / "transitions.csv"
            trace_path.write_text(trace, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(TOOLS / "parse_page_lifecycle_trace.py"),
                 str(trace_path), "--json", "--csv", str(csv_path)],
                check=False, text=True, capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["total_events"], 2)
            header = csv_path.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("classification", header)


if __name__ == "__main__":
    unittest.main()
