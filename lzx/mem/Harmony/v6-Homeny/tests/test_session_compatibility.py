from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shlex
import zipfile
from types import SimpleNamespace

from wps_v6_session import (
    LEGACY_OPERATION_FIELDS,
    NEW_OPERATION_FIELDS,
    parse_collector_report_paths,
    process_snapshot,
    report_directory,
    run_host,
    stage_baseline_semantics,
    Session,
)


class FakeDevice:
    def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
        del check, timeout_s
        if command.startswith("ps "):
            return (
                "PID PPID UID VSZ RSS ARGS\n"
                "100 1 2000 10000 1000 /system/bin/wps --bundle-name cn.wps.office.hap\n"
                "101 100 2000 5000 500 wps --type=renderer --bundle-name cn.wps.office.hap\n"
            )
        if command == "cat /proc/100/stat":
            return "100 (WPS Main) S " + " ".join(str(value) for value in range(4, 22)) + " 10000 0"
        if command == "cat /proc/101/stat":
            return "101 (WPS Renderer (CEF)) S " + " ".join(str(value) for value in range(4, 22)) + " 10001 0"
        if command == "cat /proc/100/comm":
            return "WPS Main"
        if command == "cat /proc/101/comm":
            return "WPS Renderer (CEF)"
        if command.startswith("readlink /proc/100"):
            return "/system/bin/wps"
        if command.startswith("readlink /proc/101"):
            return "/system/bin/wps-helper"
        if command.startswith("cat /proc/100/cmdline"):
            return "/system/bin/wps --bundle-name cn.wps.office.hap"
        if command.startswith("cat /proc/101/cmdline"):
            return "wps --type=renderer --bundle-name cn.wps.office.hap"
        return ""


def test_run_host_decodes_hdc_output_as_utf8_with_replacement(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="中文文档.docx")

    monkeypatch.setattr("wps_v6_session.subprocess.run", fake_run)

    result = run_host(["hdc", "list", "targets"])

    assert result.stdout == "中文文档.docx"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_status_parser_prefers_stable_lines_and_supports_legacy() -> None:
    output = "\n".join(
        [
            "Referenced 报告已写入: /old/ignored.md",
            "REPORT_MD=/new/report_pid_10.md",
            "REPORT_JSONL=/new/report_pid_10.jsonl",
        ]
    )
    assert parse_collector_report_paths(output) == {
        "MARKDOWN": ["/new/report_pid_10.md"],
        "JSONL": ["/new/report_pid_10.jsonl"],
    }
    assert parse_collector_report_paths("Referenced 报告已写入: /legacy/report.md")["MARKDOWN"] == [
        "/legacy/report.md"
    ]


def test_report_directory_uses_sample_kind_and_stage(tmp_path: Path) -> None:
    assert report_directory(tmp_path, "BASELINE", "03_write_metadata") == tmp_path / "baseline_reports" / "03_write_metadata"
    assert report_directory(tmp_path, "OPERATION", "03_write_metadata") == tmp_path / "operation_reports" / "03_write_metadata"
    assert report_directory(tmp_path, "POST_LAUNCH", "01_open_wps") == tmp_path / "post_launch_reports" / "01_open_wps"


def test_process_snapshot_enriches_starttime_comm_exe_and_roles() -> None:
    rows = process_snapshot(FakeDevice())
    assert rows[0]["process_starttime"] == 10000
    assert rows[0]["starttime_available"] is True
    assert rows[0]["process_role"] == "WPS_MAIN"
    assert rows[1]["process_role"] == "WPS_CEF_RENDERER"
    assert rows[1]["comm"] == "WPS Renderer (CEF)"
    assert rows[1]["exe_path"] == "/system/bin/wps-helper"


class ToyboxDevice:
    def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
        del check, timeout_s
        if command == "ps -A -o PID,PPID,UID,VSZ,RSS,ARGS":
            return "PID TTY TIME CMD\n1 ? 00:00 init"
        if command == "ps -ef":
            return (
                "UID PID PPID C STIME TTY TIME CMD\n"
                "20020031 31650 683 0 06:50:02 ? 00:06:19 cn.wps.office.hap\n"
            )
        if command == "cat /proc/31650/status":
            return "Name:\twps\nVmSize:\t10000 kB\nVmRSS:\t1000 kB\n"
        if command == "cat /proc/31650/stat":
            return "31650 (cn.wps.office.hap) S " + " ".join(str(value) for value in range(4, 22)) + " 12345 0"
        if command == "cat /proc/31650/comm":
            return "cn.wps.office.hap"
        if command.startswith("readlink /proc/31650"):
            return "/data/app/el1/bundle/public/cn.wps.office.hap/wps"
        if command.startswith("cat /proc/31650/cmdline"):
            return "cn.wps.office.hap"
        return ""


def test_process_snapshot_falls_back_to_toybox_ps_ef() -> None:
    rows = process_snapshot(ToyboxDevice())
    assert len(rows) == 1
    assert rows[0]["pid"] == "31650"
    assert rows[0]["ppid"] == "683"
    assert rows[0]["uid"] == "20020031"
    assert rows[0]["vsz_kb"] == "10000"
    assert rows[0]["rss_kb"] == "1000"
    assert rows[0]["process_role"] == "WPS_MAIN"


def test_new_operation_fields_are_appended_after_all_legacy_fields() -> None:
    assert LEGACY_OPERATION_FIELDS[-1] == "error"
    assert not set(LEGACY_OPERATION_FIELDS) & set(NEW_OPERATION_FIELDS)
    assert (LEGACY_OPERATION_FIELDS + NEW_OPERATION_FIELDS)[: len(LEGACY_OPERATION_FIELDS)] == LEGACY_OPERATION_FIELDS
    assert "baseline_jsonl_report" in NEW_OPERATION_FIELDS
    assert "operation_jsonl_report" in NEW_OPERATION_FIELDS
    assert "vma_mapping_status" in NEW_OPERATION_FIELDS


def test_special_stage_baseline_semantics() -> None:
    assert stage_baseline_semantics("01_open_wps") == {
        "baseline_status": "NOT_APPLICABLE",
        "baseline_unavailable_reason": "NO_PREEXISTING_WPS_PROCESS",
        "sample_semantics": "POST_LAUNCH_ACTIVITY",
        "baseline_state": "NO_PREEXISTING_WPS_PROCESS",
    }
    assert stage_baseline_semantics("06_background")["baseline_state"] == "FOREGROUND_IDLE"
    assert stage_baseline_semantics("07_foreground")["baseline_state"] == "BACKGROUND_IDLE"
    assert stage_baseline_semantics("08_reopen_saved_document")["baseline_state"] == "POST_LAUNCH_PRE_DOCUMENT_IDLE"


def test_new_word_uses_verified_3120x2080_coordinates_and_captures_evidence(monkeypatch) -> None:
    session = Session.__new__(Session)
    clicks: list[tuple[int, int]] = []
    screenshots: list[str] = []
    session.ui_click = lambda x, y: clicks.append((x, y))  # type: ignore[method-assign]
    session.capture_screen = lambda label: screenshots.append(label)  # type: ignore[method-assign]
    monkeypatch.setattr("wps_v6_session.time.sleep", lambda _seconds: None)

    session.new_word()

    assert clicks == [(420, 275), (835, 555), (1125, 600)]
    assert screenshots == ["02_new_word_after"]


def test_save_document_opens_real_word_save_icon(monkeypatch) -> None:
    session = Session.__new__(Session)
    session.args = SimpleNamespace(test_serial="WPS-TEST-0001")
    clicks: list[tuple[int, int]] = []
    session.ui_click = lambda x, y: clicks.append((x, y))  # type: ignore[method-assign]
    session.capture_screen = lambda _label: None  # type: ignore[method-assign]
    session.list_documents = lambda: []  # type: ignore[method-assign]
    session.find_saved_document = lambda wait_s=0.0: {  # type: ignore[method-assign]
        "path": "/storage/media/100/local/files/Docs/Desktop/test.docx",
        "size_bytes": 123,
        "mtime": "2026-07-17 11:00:00",
    }
    session.verify_document_content = lambda _path: {"test_serial": True}  # type: ignore[method-assign]
    monkeypatch.setattr("wps_v6_session.time.sleep", lambda _seconds: None)

    session.save_document()

    assert clicks[0] == (195, 115)


def test_ui_text_payload_has_no_synthetic_prefix(monkeypatch) -> None:
    session = Session.__new__(Session)
    commands: list[str] = []

    class RecordingDevice:
        def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
            del check, timeout_s
            commands.append(command)
            return ""

    session.device = RecordingDevice()
    monkeypatch.setattr("wps_v6_session.time.sleep", lambda _seconds: None)

    session.ui_text_payload("WPS_memory_probe")

    assert commands == ["uitest uiInput text WPS_memory_probe"]


def test_ui_text_uses_empirically_safe_chunks_and_commits_each_chunk() -> None:
    session = Session.__new__(Session)
    chunks: list[str] = []
    keys: list[str] = []
    session.ui_text_payload = lambda value: chunks.append(value)  # type: ignore[method-assign]
    session.ui_key = lambda key: keys.append(key)  # type: ignore[method-assign]
    payload = "A" * 170

    session.ui_text(payload)

    assert [len(chunk) for chunk in chunks] == [60, 60, 50]
    assert "".join(chunks) == payload
    assert keys == ["2054", "2054", "2054"]


def test_ui_text_chunks_never_start_later_payload_with_underscore() -> None:
    session = Session.__new__(Session)
    payload = "A" * 60 + "_aggregates_" + "B" * 60

    chunks = session.ui_text_chunks(payload)

    assert "".join(chunks) == payload
    assert max(map(len, chunks)) <= 60
    assert all(chunk[0].isalnum() for chunk in chunks)


def test_ui_commit_chunks_preserves_text_enter_and_settle_order() -> None:
    session = Session.__new__(Session)
    commands: list[str] = []

    class RecordingDevice:
        def shell(self, command: str, *, timeout_s: float = 180.0) -> str:
            del timeout_s
            commands.append(command)
            return ""

    session.device = RecordingDevice()

    session.ui_commit_chunks(["Alpha", "Beta"])

    assert len(commands) == 1
    assert commands[0].splitlines() == [
        "uitest uiInput text Alpha",
        "sleep 0.25",
        "uitest uiInput keyEvent 2054",
        "sleep 0.25",
        "uitest uiInput text Beta",
        "sleep 0.25",
        "uitest uiInput keyEvent 2054",
        "sleep 0.25",
    ]


def test_heavy_edit_uses_safe_chunks_and_commits_every_chunk() -> None:
    session = Session.__new__(Session)
    session.args = SimpleNamespace(
        editor_x=1100,
        editor_y=1020,
        heavy_repeats=2,
        test_serial="WPS-TEST-0001",
    )
    chunks: list[str] = []
    clicks: list[tuple[int, int]] = []
    session.ui_click = lambda x, y: clicks.append((x, y))  # type: ignore[method-assign]
    session.ui_commit_chunks = lambda values: chunks.extend(values)  # type: ignore[method-assign]
    session.ui_text = lambda _value: None  # type: ignore[method-assign]
    session.ui_key = lambda _key: None  # type: ignore[method-assign]
    session.ui_swipe = lambda _x1, _y1, _x2, _y2: None  # type: ignore[method-assign]

    session.heavy_edit_scroll()

    block = (
        "WPS_memory_profiling_stress_paragraph_repeated_text_creates_a_multi_page_Word_document_"
        "for_observing_layout_rendering_cache_and_process_memory_behavior_test_serial_"
        "WPS-TEST-0001_controlled_workload_"
    )
    assert "".join(chunks) == block * 2
    assert chunks and max(map(len, chunks)) <= 60
    per_block = len(session.ui_text_chunks(block))
    assert chunks[:per_block] == chunks[per_block:]
    assert clicks == [(980, 940), (1220, 1100)]


def test_verify_document_content_checks_complete_stress_payload(tmp_path: Path) -> None:
    session = Session.__new__(Session)
    session.args = SimpleNamespace(test_serial="WPS-TEST-0001", heavy_repeats=2)
    block = session.heavy_workload_block()
    text = (
        "Test_serial_WPS-TEST-0001 Exact_time "
        "Purpose_measure_WPS_related_process_RSS_PSS_Referenced_and_Swap_"
        "during_a_real_Word_workflow "
        "Operation_chain_open_WPS_new_Word_write_metadata_heavy_edit_line_breaks_"
        "page_scroll_cursor_move_save_background_foreground_close_reopen_saved_"
        "document_reopen_edit_scroll_close "
        "Preliminary_conclusion_profiling_evidence_only_compare_stage_aggregates_"
        "and_do_not_infer_reclamation_from_Referenced_alone " + block * 2
    )
    source = tmp_path / "source.docx"
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text[:200]}</w:t></w:r>"
        f"<w:r><w:t>{text[200:]}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", xml)

    class DocumentDevice:
        def recv(self, _remote: str, local: Path) -> str:
            local.write_bytes(source.read_bytes())
            return "ok"

    session.device = DocumentDevice()

    markers = session.verify_document_content("/device/test.docx")

    assert markers["heavy_workload_complete"] is True
    assert all(markers.values())


def test_rename_saved_document_preserves_content_verification_metadata() -> None:
    session = Session.__new__(Session)
    source = "/storage/media/100/local/files/Docs/Desktop/xWPS.docx"
    destination = "/storage/media/100/local/files/Docs/Desktop/WPS_memory_test_20260717_120000.docx"
    session.session_timestamp = "20260717_120000"
    session.saved_document = {
        "path": source,
        "size_bytes": 100,
        "mtime": "before",
        "content_markers_verified": {"test_serial": True, "purpose": True},
    }
    session.device = FakeDevice()
    session.list_documents = lambda: [  # type: ignore[method-assign]
        {"path": destination, "size_bytes": 101, "mtime": "after"}
    ]

    renamed = session.rename_saved_document()

    assert renamed["content_markers_verified"] == {"test_serial": True, "purpose": True}
    assert renamed["original_path"] == source
    assert renamed["final_path"] == destination


def test_open_saved_document_uses_exact_filename_picker_path(monkeypatch) -> None:
    session = Session.__new__(Session)
    final_path = "/storage/media/100/local/files/Docs/Desktop/WPS_memory_test_20260717_120000.docx"
    session.args = SimpleNamespace(launch_wait_s=0.0)
    session.saved_document = {
        "path": final_path,
        "final_path": final_path,
        "size_bytes": 101,
        "content_markers_verified": {"test_serial": True},
    }
    clicks: list[tuple[int, int]] = []
    screenshots: list[str] = []
    commands: list[str] = []
    session.ui_click = lambda x, y: clicks.append((x, y))  # type: ignore[method-assign]
    session.capture_screen = lambda label: screenshots.append(label)  # type: ignore[method-assign]
    session.ui_key = lambda key: commands.append(f"key:{key}")  # type: ignore[method-assign]
    session.snapshot = lambda: [{"pid": "100"}]  # type: ignore[method-assign]
    session.start_wps = lambda: None  # type: ignore[method-assign]
    session.verify_document_content = lambda _path: {"test_serial": True}  # type: ignore[method-assign]
    session.list_documents = lambda: [  # type: ignore[method-assign]
        {"path": final_path, "size_bytes": 101, "mtime": "after"}
    ]

    class RecordingDevice:
        def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
            del check, timeout_s
            commands.append(command)
            return ""

    session.device = RecordingDevice()
    monkeypatch.setattr("wps_v6_session.time.sleep", lambda _seconds: None)

    session.open_saved_document(start_wps=False)

    assert clicks == [(420, 390), (670, 980), (1850, 1535)]
    assert any(
        command == "uitest uiInput text WPS_memory_test_20260717_120000.docx"
        for command in commands
    )
    assert commands.count("key:2054") == 2
    assert screenshots == ["08_reopen_picker", "08_reopen_after"]
    assert session.saved_document["reopen_requested_path"] == final_path
    assert session.saved_document["reopen_picker_exact_name"] is True
    assert session.reopen_verified is True


def test_reopen_edit_records_ui_only_marker_without_claiming_persistence() -> None:
    session = Session.__new__(Session)
    session.args = SimpleNamespace(editor_x=1100, editor_y=1020)
    session.session_timestamp = "20260717_120000"
    session.saved_document = {"final_path": "/device/test.docx"}
    session.reopen_verified = True
    screenshots: list[str] = []
    typed: list[str] = []
    session.ui_click = lambda _x, _y: None  # type: ignore[method-assign]
    session.ui_text = lambda value: typed.append(value)  # type: ignore[method-assign]
    session.ui_swipe = lambda _x1, _y1, _x2, _y2: None  # type: ignore[method-assign]
    session.ui_key = lambda _key: None  # type: ignore[method-assign]
    session.capture_screen = lambda label: screenshots.append(label)  # type: ignore[method-assign]

    session.reopen_edit_scroll()

    assert typed == ["Reopen_verification_20260717_120000\n"]
    assert screenshots == ["09_reopen_marker_ui"]
    assert session.saved_document["reopen_ui_marker_evidence"] == "SCREENSHOT_UI_ONLY"
    assert session.saved_document["reopen_marker_persistence"] == "NOT_REQUIRED_FOR_STAGE_09"
    assert "reopen_marker_verified" not in session.saved_document


class RowsWriter:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def writerow(self, row: dict[str, object]) -> None:
        self.rows.append(row)


class FlushOnly:
    def flush(self) -> None:
        pass


class SampleDevice:
    def __init__(self) -> None:
        self.remote: dict[str, bytes] = {}

    def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
        del check, timeout_s
        if " --app " in command and "--jsonl-output" in command:
            parts = shlex.split(command)
            md = parts[parts.index("-o") + 1]
            jsonl = parts[parts.index("--jsonl-output") + 1]
            self.remote[md] = (
                "# Referenced 操作后访问定位报告\n\n"
                "| 项目 | 值 |\n| --- | --- |\n| PID | `10` |\n| 进程名 | `wps` |\n"
                "| Rss | `4 KiB` |\n| Pss | `4 KiB` |\n| Referenced | `4 KiB / 1 页` |\n| Swap | `0 KiB` |\n"
            ).encode()
            item = {
                "schema_version": "homeny.vma.v1", "record_type": "vma", "pid": 10,
                "page_size_bytes": 4096, "start_address": 4096, "end_address": 8192,
                "address_size_bytes": 4096, "permissions": "rw-p", "file_offset_bytes": 0,
                "file_offset_end_bytes": 4096, "device": "00:00", "dev_major": 0, "dev_minor": 0,
                "inode": 0, "path": "", "normalized_path": "", "path_deleted": False,
                "segment": "AnonPage other", "mapping_type": "ANON_OTHER", "size_kib": 4,
                "rss_kib": 4, "referenced_kib": 4, "referenced_pages": 1,
                "referenced_size_ratio": 1.0, "referenced_rss_ratio": 1.0,
            }
            self.remote[jsonl] = (json.dumps(item) + "\n").encode()
            return f"REPORT_MD={md}\nREPORT_JSONL={jsonl}"
        if command.startswith("sha256sum "):
            path = shlex.split(command)[1]
            return hashlib.sha256(self.remote[path]).hexdigest()
        return ""

    def recv(self, remote: str, local: Path) -> str:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.remote[remote])
        return "ok"


def make_sample_session(tmp_path: Path) -> Session:
    session = Session.__new__(Session)
    session.local_out = tmp_path
    session.device_out = "/remote/session"
    session.device_bin = "/remote/mem_analyze-v6"
    session.device = SampleDevice()
    session.hashes = RowsWriter()
    session.hash_file = FlushOnly()
    session.device_report_hashes = {}
    session.local_report_hashes = {}
    session.report_records = []
    return session


def test_sample_pulls_both_formats_by_kind_and_preserves_report_semantics(tmp_path: Path) -> None:
    session = make_sample_session(tmp_path)
    processes = [{"pid": "10", "process_role": "WPS_MAIN", "process_starttime": 100}]
    baseline = session.sample(3, "03_write_metadata", "BASELINE", processes)
    operation = session.sample(3, "03_write_metadata", "OPERATION", processes)

    assert baseline["report"] == ""
    assert baseline["baseline_report_count"] == 1
    assert Path(baseline["baseline_report"]).parent == tmp_path / "baseline_reports" / "03_write_metadata"
    assert Path(baseline["baseline_jsonl_report"]).is_file()
    assert operation["report"] == operation["operation_report"]
    assert Path(operation["operation_jsonl_report"]).parent == tmp_path / "operation_reports" / "03_write_metadata"
    assert {row["sample_kind"] for row in session.hashes.rows} == {"BASELINE", "OPERATION"}
    assert {row["report_format"] for row in session.hashes.rows} == {"MARKDOWN", "JSONL"}
    assert all(row["pid"] == "10" for row in session.hashes.rows)
