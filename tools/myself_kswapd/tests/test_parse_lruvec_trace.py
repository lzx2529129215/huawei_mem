import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(ROOT.parent))

from parse_lruvec_trace import ErrorCode, parse_trace_text, parse_trace


class LruvecTraceParserTest(unittest.TestCase):
    def test_valid_events_are_structured_and_merged_by_sequence(self):
        result = parse_trace(FIXTURES / "lruvec_snapshot.log")
        self.assertFalse(result.errors)
        self.assertEqual(
            [event.event for event in result.events],
            ["request_begin", "lruvec_snapshot", "lruvec_snapshot",
             "lruvec_snapshot", "lruvec_snapshot"],
        )
        snapshots = [event for event in result.events
                     if event.event == "lruvec_snapshot"]
        self.assertEqual([event.fields["snapshot_seq"] for event in snapshots],
                         [1, 2, 3, 4])
        self.assertEqual(snapshots[0].fields["isolated_scope"], 2)

    def test_request_event_does_not_require_snapshot_identity(self):
        result = parse_trace_text(
            "myself_kswapd:request_begin: request_id=9 nid=2 "
            "requested_order=0 highest_zoneidx=2 gfp_mask=0x20 "
            "initial_boost_pages=0 boosted=0\n"
        )
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].event, "request_begin")
        self.assertFalse(result.errors)

    def test_real_ftrace_event_names_are_parsed(self):
        result = parse_trace(FIXTURES / "real_ftrace_lruvec_trace.txt")
        self.assertFalse(result.errors)
        self.assertEqual([event.event for event in result.events],
                         ["lruvec_snapshot"])

    def test_all_supported_lruvec_aliases_and_mixed_formats_are_parsed(self):
        payload = (
            "snapshot_seq={seq} timestamp_ns={seq} request_id=1 priority_seq=1 "
            "scan_seq={seq} mode=0 memcg_id=1 nid=0 memcg_css_id=1 "
            "reclaim_source=0 stage=0 consistency=0 priority=1 lru_scope=1 "
            "isolated_scope=2 inactive_anon=1 active_anon=1 inactive_file=1 "
            "active_file=1 isolated_anon=1 isolated_file=1 scanned_total=0 "
            "reclaimed_total=0 field_valid_mask=0xff validation_flags=0"
        )
        text = "\n".join((
            "cpu=1 ... myself_kswapd:lruvec_snapshot: " + payload.format(seq=1),
            "worker-7 [00] .... 1.002: lruvec_snapshot: " + payload.format(seq=2),
            "worker-7 [00] .... 1.003: myself_kswapd_lruvec_snapshot: " + payload.format(seq=3),
        ))
        result = parse_trace_text(text)
        self.assertFalse(result.errors)
        self.assertEqual(len(result.events), 3)

    def test_unknown_similar_event_and_payload_text_are_not_parsed(self):
        result = parse_trace_text(
            "worker-7 [00] .... 1.002: lruvec_snapshot_extra: request_id=1\n"
            "worker-7 [00] .... 1.003: other_event: note=lruvec_snapshot:\n"
        )
        self.assertFalse(result.events)
        self.assertFalse(result.errors)

    def test_missing_field_is_reported_and_parser_continues(self):
        text = (
            "myself_kswapd:lruvec_snapshot: snapshot_seq=1 timestamp_ns=1 "
            "request_id=1 priority_seq=1 scan_seq=1 mode=0 memcg_id=1 "
            "nid=0 memcg_css_id=1 reclaim_source=2 stage=0 consistency=0 "
            "priority=1 lru_scope=1 isolated_scope=2 inactive_anon=1\n"
            "myself_kswapd:lruvec_snapshot: "
            "snapshot_seq=2 timestamp_ns=2 request_id=0 priority_seq=0 "
            "scan_seq=0 mode=1 memcg_id=18446744073709551615 nid=0 "
            "memcg_css_id=0 reclaim_source=3 stage=2 consistency=0 priority=-1 "
            "lru_scope=2 isolated_scope=2 inactive_anon=1 active_anon=1 "
            "inactive_file=1 active_file=1 isolated_anon=1 isolated_file=1 "
            "scanned_total=0 reclaimed_total=0 field_valid_mask=0x3f "
            "validation_flags=0\n"
        )
        result = parse_trace_text(text)
        self.assertEqual(len(result.events), 1)
        self.assertIn(ErrorCode.MISSING_FIELD, {issue.code for issue in result.errors})

    def test_invalid_enum_overflow_duplicate_and_gap(self):
        base = (
            "myself_kswapd:lruvec_snapshot: snapshot_seq={seq} timestamp_ns=1 "
            "request_id=1 priority_seq=1 scan_seq=1 mode={mode} memcg_id=1 "
            "nid=0 memcg_css_id=1 reclaim_source=2 stage=0 consistency=0 "
            "priority=1 lru_scope=1 isolated_scope=2 inactive_anon=1 "
            "active_anon=1 inactive_file=1 active_file=1 isolated_anon=1 "
            "isolated_file=1 scanned_total=0 reclaimed_total=0 "
            "field_valid_mask=0xff validation_flags=0\n"
        )
        text = base.format(seq=1, mode=9)
        text += base.format(seq=3, mode=0)
        text += base.format(seq=3, mode=0)
        text += base.format(seq=18446744073709551616, mode=0)
        result = parse_trace_text(text)
        codes = {issue.code for issue in result.errors}
        self.assertIn(ErrorCode.INVALID_MODE, codes)
        self.assertIn(ErrorCode.DUPLICATE_SEQUENCE, codes)
        self.assertIn(ErrorCode.PROVISIONAL_GAP, codes)
        self.assertIn(ErrorCode.INTEGER_OVERFLOW, codes)

    def test_invalid_scope_is_reported(self):
        text = (
            "myself_kswapd:lruvec_snapshot: snapshot_seq=1 timestamp_ns=1 "
            "request_id=1 priority_seq=1 scan_seq=1 mode=0 memcg_id=1 nid=0 "
            "memcg_css_id=1 reclaim_source=2 stage=0 consistency=0 priority=1 "
            "lru_scope=2 isolated_scope=1 inactive_anon=1 active_anon=1 "
            "inactive_file=1 active_file=1 isolated_anon=1 isolated_file=1 "
            "scanned_total=0 reclaimed_total=0 field_valid_mask=0xff "
            "validation_flags=0\n"
        )
        result = parse_trace_text(text)
        self.assertIn(ErrorCode.INVALID_SCOPE, {issue.code for issue in result.errors})

    def test_invalid_source_and_stage_are_reported(self):
        text = (
            "myself_kswapd:lruvec_snapshot: snapshot_seq=1 timestamp_ns=1 "
            "request_id=1 priority_seq=1 scan_seq=1 mode=0 memcg_id=1 nid=0 "
            "memcg_css_id=1 reclaim_source=8 stage=8 consistency=0 priority=1 "
            "lru_scope=1 isolated_scope=2 inactive_anon=1 active_anon=1 "
            "inactive_file=1 active_file=1 isolated_anon=1 isolated_file=1 "
            "scanned_total=0 reclaimed_total=0 field_valid_mask=0xff "
            "validation_flags=0\n"
        )
        result = parse_trace_text(text)
        codes = {issue.code for issue in result.errors}
        self.assertIn(ErrorCode.INVALID_SOURCE, codes)
        self.assertIn(ErrorCode.INVALID_STAGE, codes)


if __name__ == "__main__":
    unittest.main()
