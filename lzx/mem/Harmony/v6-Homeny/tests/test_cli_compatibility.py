from __future__ import annotations

from run_wps_workload import build_session_command, parse_args


def test_repeated_workload_cli_passes_baseline_configuration() -> None:
    args = parse_args([
        "--target", "device-one",
        "--baseline-window-s", "7.5",
        "--vma-mapping-config", "/tmp/config.json",
        "--no-idle-baseline",
    ])
    command = build_session_command(args, "/tmp/session.py", "/tmp/trial", "session-one")
    assert command[command.index("--baseline-window-s") + 1] == "7.5"
    assert command[command.index("--vma-mapping-config") + 1] == "/tmp/config.json"
    assert "--no-idle-baseline" in command


def test_old_repeated_workload_command_defaults_remain_valid() -> None:
    args = parse_args(["--repeats", "3"])
    assert args.repeats == 3
    assert args.target == ""
    assert args.baseline_window_s == 5.0
    assert args.idle_baseline is True

    command = build_session_command(args, "/tmp/session.py", "/tmp/trial", "session-one")
    assert "--target" not in command
