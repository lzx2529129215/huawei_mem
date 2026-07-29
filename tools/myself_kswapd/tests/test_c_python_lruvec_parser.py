import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USER_ROOT = ROOT / "用户态模拟器" / "v1"
FIXTURE = ROOT / "tools" / "myself_kswapd" / "tests" / "fixtures" / "lruvec_snapshot.log"
sys.path.insert(0, str(ROOT / "tools" / "myself_kswapd"))
from parse_lruvec_trace import ErrorCode, parse_trace_text


PROBE = r'''
#include "myself_kswapd/kernel_lruvec_snapshot.h"
#include <stdio.h>

int main(void)
{
    char line[8192];
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;
    while (fgets(line, sizeof(line), stdin) != NULL) {
        printf("%d\n", kernel_lruvec_parse_trace_line(line, &snapshot, &error));
    }
    return 0;
}
'''


class CAndPythonParserTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp.name)
        probe_source = temp_root / "probe.c"
        probe_source.write_text(PROBE, encoding="utf-8")
        self.binary = temp_root / "probe"
        subprocess.run(
            [
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(USER_ROOT / "include"),
                str(USER_ROOT / "src" / "l02" / "lruvec_trace_parser.c"),
                str(probe_source), "-o", str(self.binary),
            ],
            check=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def probe(self, text):
        result = subprocess.run(
            [str(self.binary)], input=text, text=True,
            capture_output=True, check=True,
        )
        return [int(value) for value in result.stdout.splitlines()]

    def test_fixture_valid_snapshot_lines_match(self):
        text = FIXTURE.read_text(encoding="utf-8")
        python_result = parse_trace_text(text)
        statuses = self.probe(text)
        snapshot_lines = [
            line for line in text.splitlines()
            if "myself_kswapd:lruvec_snapshot:" in line
        ]
        self.assertEqual(len(statuses), len(text.splitlines()))
        self.assertTrue(snapshot_lines)
        self.assertFalse(python_result.errors)
        self.assertTrue(all(status == 0 for status in statuses if status != 1))

    def test_error_matrix_matches_python_categories(self):
        valid = next(
            line for line in FIXTURE.read_text(encoding="utf-8").splitlines()
            if "myself_kswapd:lruvec_snapshot:" in line
        )
        cases = [
            valid.replace("mode=0", "mode=9"),
            valid.replace("lru_scope=1", "lru_scope=2"),
            valid.replace("timestamp_ns=101", "timestamp_ns=18446744073709551616"),
            valid.replace(" inactive_anon=10", ""),
        ]
        python_codes = []
        status_map = {
            ErrorCode.INVALID_MODE: 4,
            ErrorCode.INVALID_SCOPE: 7,
            ErrorCode.INTEGER_OVERFLOW: 5,
            ErrorCode.MISSING_FIELD: 2,
        }
        for case in cases:
            python_result = parse_trace_text(case + "\n")
            self.assertTrue(python_result.errors)
            python_codes.append(status_map[python_result.errors[0].code])
        self.assertEqual(self.probe("\n".join(cases) + "\n"), python_codes)


if __name__ == "__main__":
    unittest.main()
