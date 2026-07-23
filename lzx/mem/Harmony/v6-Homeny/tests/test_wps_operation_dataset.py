import json
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from build_wps_vma_dataset import (
    ANON_SLOTS,
    FILE_SLOTS,
    VECTOR_DIM,
    build_dataset,
    build_vector,
    l2_normalize,
    map_fixed_window_sequence,
    parse_vma_report,
    stable_hash_index,
)


REPORT = """# Referenced 操作后访问定位报告

| PID | `123` |
| 进程名 | `wps_test` |

## Referenced VMA 定位

| VMA | 一级段 | 权限 | Size(KiB) | Rss(KiB) | Pss(KiB) | Referenced(KiB) | Referenced页 | Referenced/Size | Referenced/Rss | 路径 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `1000-2000` | FilePage other | `r--p` | 4 | 4 | 4 | 8 | 2 | 100.00% | 100.00% | `/data/wps/lib.so` |
| `3000-4000` | AnonPage other | `rw-p` | 4 | 4 | 4 | 4 | 1 | 100.00% | 100.00% | `[anon:v8]` |
"""


class WpsOperationDatasetTest(unittest.TestCase):
    def test_catalog_ids_are_unique_and_complete(self):
        catalog_path = Path(__file__).parents[1] / "wps_operation_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        labels = catalog["operations"]
        self.assertEqual([item["label_id"] for item in labels], list(range(18)))
        self.assertEqual(len({item["label"] for item in labels}), 18)

    def test_catalog_covers_common_writer_operations(self):
        catalog_path = Path(__file__).parents[1] / "wps_operation_catalog.json"
        labels = {
            item["label"]
            for item in json.loads(catalog_path.read_text(encoding="utf-8"))["operations"]
        }
        self.assertGreaterEqual(len(labels), 10)
        self.assertTrue({
            "NEW_DOCUMENT", "WRITE_TEXT", "SELECT_ALL", "COPY_SELECTION",
            "PASTE_SELECTION", "CUT_SELECTION", "UNDO_EDIT", "REDO_EDIT",
            "FIND_TEXT", "REPLACE_TEXT", "INSERT_PAGE_BREAK", "INSERT_TABLE",
            "FORMAT_BOLD", "FORMAT_ITALIC", "FORMAT_UNDERLINE", "ALIGN_CENTER",
            "SAVE_DOCUMENT", "CLOSE_DOCUMENT",
        } <= labels)

    def test_hash_is_deterministic_and_namespaced(self):
        file_index = stable_hash_index("FILE", "/data/wps/lib.so")
        anon_index = stable_hash_index("ANON", "[anon:v8]")
        self.assertEqual(file_index, stable_hash_index("FILE", "/data/wps/lib.so"))
        self.assertEqual(anon_index, stable_hash_index("ANON", "[anon:v8]"))
        self.assertTrue(0 <= file_index < FILE_SLOTS)
        self.assertTrue(FILE_SLOTS <= anon_index < FILE_SLOTS + ANON_SLOTS)

    def test_report_parser_uses_semantic_keys_not_addresses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.md"
            path.write_text(REPORT, encoding="utf-8")
            rows = parse_vma_report(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["feature_namespace"] for row in rows}, {"FILE", "ANON"})
        self.assertTrue(all("1000-2000" not in row["feature_key"] for row in rows))

    def test_action_and_post_action_use_maximum_excess(self):
        baseline = {"feature_pages": {"FILE\tstable": 3.0, "ANON\tbaseline_only": 4.0}}
        action = {"feature_pages": {"FILE\tstable": 9.0, "ANON\tbaseline_only": 4.0}}
        post = {"feature_pages": {"FILE\tstable": 5.0, "ANON\tnew": 2.0}}
        result = map_fixed_window_sequence(
            operation_execution_id="exec",
            operation_id="WRITE_TEXT",
            baseline_group_id="baseline",
            baseline_windows=[baseline, baseline],
            operation_windows=[
                {"segment_label": "ACTION", **action},
                {"segment_label": "POST_ACTION", **post},
            ],
        )
        features = {row["feature_key"]: row for row in result["aggregated_features"]}
        self.assertEqual(features["stable"]["aggregated_excess_pages"], 6.0)
        self.assertEqual(features["stable"]["post_action_excess_pages"], 2.0)
        self.assertNotIn("baseline_only", features)
        self.assertEqual(features["new"]["aggregated_excess_pages"], 2.0)

    def test_vectors_are_fixed_dimension_and_l2_normalized(self):
        raw = build_vector({"/data/wps/lib.so": 8}, {"[anon:v8]": 4})
        self.assertEqual(len(raw), VECTOR_DIM)
        self.assertEqual(len(l2_normalize(raw)), VECTOR_DIM)
        self.assertAlmostEqual(sum(value * value for value in l2_normalize(raw)), 1.0)
        self.assertEqual(sum(build_vector({}, {})), 0.0)

    def test_manifest_labels_and_vectors_have_same_sample_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mapping = map_fixed_window_sequence(
                operation_execution_id="exec",
                operation_id="NEW_DOCUMENT",
                baseline_group_id="baseline",
                baseline_windows=[{"window_id": "b1", "feature_pages": {}}, {"window_id": "b2", "feature_pages": {}}],
                operation_windows=[
                    {"window_id": "a1", "segment_label": "ACTION", "feature_pages": {"FILE\tnew": 2.0}},
                    {"window_id": "p1", "segment_label": "POST_ACTION", "feature_pages": {}},
                ],
            )
            sequence = {
                "sample_id": "wps_trial_001_new_document",
                "trial_id": "trial_001",
                "trial_dir": "trial_001",
                "session_id": "session_001",
                "label_id": 0,
                "operation_label": "NEW_DOCUMENT",
                "precondition": "WPS_HOME_IDLE",
                "execution_id": "exec",
                "status": "success",
                "baseline_window_count": 2,
                "action_window_s": 15,
                "post_window_s": 5,
                "baseline_windows": [{"window_id": "b1", "status": "success", "report_paths": []}, {"window_id": "b2", "status": "success", "report_paths": []}],
                "operation_windows": [{"window_id": "a1", "status": "success", "report_paths": []}, {"window_id": "p1", "status": "success", "report_paths": []}],
                "sequence": mapping,
            }
            (root / "operation_window_sequences.jsonl").write_text(json.dumps(sequence) + "\n", encoding="utf-8")
            build_dataset(root)
            with (root / "dataset_manifest.csv").open(encoding="utf-8", newline="") as handle:
                manifest_ids = {row["sample_id"] for row in csv.DictReader(handle)}
            with (root / "labels.csv").open(encoding="utf-8", newline="") as handle:
                label_ids = {row["sample_id"] for row in csv.DictReader(handle)}
            with (root / "vma_vectors_raw.csv").open(encoding="utf-8", newline="") as handle:
                vector_ids = {row["sample_id"] for row in csv.DictReader(handle)}
        self.assertEqual(manifest_ids, label_ids)
        self.assertEqual(manifest_ids, vector_ids)
        self.assertEqual(len(next(iter(vector_ids))), len("wps_trial_001_new_document"))


if __name__ == "__main__":
    unittest.main()
