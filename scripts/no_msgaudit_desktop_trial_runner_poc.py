from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parent.parent


def _now_slug() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S")


def _default_trial_dir() -> Path:
    return ROOT_DIR / "data" / "no_msgaudit_desktop_agent" / "trials" / _now_slug()


def _run_command(command: list[str], *, stdout_path: Path, stderr_path: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return result


def _parse_json_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            return payload
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _capture_command(args: argparse.Namespace, *, snapshot_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "no_msgaudit_capture_wecom_snapshot_poc.py"),
        "--app-name",
        args.app_name,
        "--capture-method",
        args.capture_method,
        "--snapshot-dir",
        str(snapshot_dir),
        "--prefix",
        args.snapshot_prefix,
        "--iterations",
        str(args.capture_iterations),
        "--interval-seconds",
        str(args.capture_interval_seconds),
    ]
    if args.capture_source_text_file:
        command.extend(["--source-text-file", str(args.capture_source_text_file)])
    return command


def _scan_command(args: argparse.Namespace, *, snapshot_dir: Path, cursor_file: Path, scan_log: Path) -> list[str]:
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "no_msgaudit_desktop_scan_poc.py"),
        "--ignore-state",
        "--group-targets-json",
        str(args.group_targets_json),
        "--desktop-accessibility-tree-dir",
        str(snapshot_dir),
        "--follow-snapshot-dir",
        "--events-from-accessibility-tree",
        "--snapshot-cursor-file",
        str(cursor_file),
        "--iterations",
        str(args.scan_iterations),
        "--interval-seconds",
        str(args.scan_interval_seconds),
        "--out",
        str(scan_log),
    ]
    for assistant_name in args.assistant_name:
        command.extend(["--assistant-name", assistant_name])
    return command


def _health_command(args: argparse.Namespace, *, scan_log: Path) -> list[str]:
    return [
        sys.executable,
        str(ROOT_DIR / "scripts" / "no_msgaudit_scan_health_poc.py"),
        "--log-jsonl",
        str(scan_log),
        "--max-heartbeat-age-seconds",
        str(args.health_max_heartbeat_age_seconds),
    ]


def _trial_report_command(args: argparse.Namespace, *, scan_log: Path) -> list[str]:
    return [
        sys.executable,
        str(ROOT_DIR / "scripts" / "no_msgaudit_trial_report_poc.py"),
        "--log-jsonl",
        str(scan_log),
        "--group-targets-json",
        str(args.group_targets_json),
        "--min-duration-seconds",
        str(args.min_duration_seconds),
        "--min-heartbeat-count",
        str(args.min_heartbeat_count),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: run capture, scan, health check, and trial report for the no-message-audit desktop path."
    )
    parser.add_argument("--trial-dir", type=Path, default=None)
    parser.add_argument("--app-name", default="企业微信")
    parser.add_argument("--assistant-name", action="append", default=[])
    parser.add_argument(
        "--group-targets-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "multi_group_targets.json",
    )
    parser.add_argument("--capture-method", choices=["swift-ax", "applescript"], default="swift-ax")
    parser.add_argument("--capture-source-text-file", type=Path, default=None)
    parser.add_argument("--capture-iterations", type=int, default=31)
    parser.add_argument("--capture-interval-seconds", type=float, default=2.0)
    parser.add_argument("--snapshot-prefix", default="wecom-live")
    parser.add_argument("--scan-iterations", type=int, default=31)
    parser.add_argument("--scan-interval-seconds", type=float, default=2.0)
    parser.add_argument("--health-max-heartbeat-age-seconds", type=int, default=60)
    parser.add_argument("--min-duration-seconds", type=int, default=60)
    parser.add_argument("--min-heartbeat-count", type=int, default=31)
    args = parser.parse_args()

    if args.capture_iterations < 1:
        parser.error("--capture-iterations must be >= 1")
    if args.scan_iterations < 1:
        parser.error("--scan-iterations must be >= 1")
    if args.capture_interval_seconds < 0:
        parser.error("--capture-interval-seconds must be >= 0")
    if args.scan_interval_seconds < 0:
        parser.error("--scan-interval-seconds must be >= 0")
    if args.health_max_heartbeat_age_seconds < 0:
        parser.error("--health-max-heartbeat-age-seconds must be >= 0")
    if args.min_duration_seconds < 0:
        parser.error("--min-duration-seconds must be >= 0")
    if args.min_heartbeat_count < 1:
        parser.error("--min-heartbeat-count must be >= 1")

    trial_dir = args.trial_dir or _default_trial_dir()
    snapshot_dir = trial_dir / "accessibility_snapshots"
    cursor_file = trial_dir / "snapshot_cursor.json"
    scan_log = trial_dir / "desktop_scan_log.jsonl"
    health_report_path = trial_dir / "health_report.json"
    trial_report_path = trial_dir / "trial_report.json"
    trial_dir.mkdir(parents=True, exist_ok=True)

    capture_result = _run_command(
        _capture_command(args, snapshot_dir=snapshot_dir),
        stdout_path=trial_dir / "capture_stdout.jsonl",
        stderr_path=trial_dir / "capture_stderr.txt",
    )

    scan_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="capture_failed")
    if capture_result.returncode == 0:
        scan_result = _run_command(
            _scan_command(args, snapshot_dir=snapshot_dir, cursor_file=cursor_file, scan_log=scan_log),
            stdout_path=trial_dir / "scan_stdout.jsonl",
            stderr_path=trial_dir / "scan_stderr.txt",
        )
    else:
        (trial_dir / "scan_stdout.jsonl").write_text("", encoding="utf-8")
        (trial_dir / "scan_stderr.txt").write_text("capture_failed\n", encoding="utf-8")

    health_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="scan_failed")
    health_report: dict[str, Any] = {}
    if scan_result.returncode == 0:
        health_result = _run_command(
            _health_command(args, scan_log=scan_log),
            stdout_path=trial_dir / "health_stdout.json",
            stderr_path=trial_dir / "health_stderr.txt",
        )
        health_report = _parse_json_stdout(health_result.stdout)
    _write_json(health_report_path, health_report)

    trial_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="scan_failed")
    trial_report: dict[str, Any] = {}
    if scan_result.returncode == 0:
        trial_result = _run_command(
            _trial_report_command(args, scan_log=scan_log),
            stdout_path=trial_dir / "trial_report_stdout.json",
            stderr_path=trial_dir / "trial_report_stderr.txt",
        )
        trial_report = _parse_json_stdout(trial_result.stdout)
    _write_json(trial_report_path, trial_report)

    summary = {
        "type": "desktop_trial_summary",
        "ok": (
            capture_result.returncode == 0
            and scan_result.returncode == 0
            and health_result.returncode == 0
            and trial_result.returncode == 0
            and bool(health_report.get("ok"))
            and bool(trial_report.get("ok"))
        ),
        "trial_dir": str(trial_dir),
        "snapshot_dir": str(snapshot_dir),
        "scan_log": str(scan_log),
        "health_report": str(health_report_path),
        "trial_report": str(trial_report_path),
        "capture_returncode": capture_result.returncode,
        "scan_returncode": scan_result.returncode,
        "health_returncode": health_result.returncode,
        "trial_returncode": trial_result.returncode,
        "health_ok": bool(health_report.get("ok")),
        "trial_ok": bool(trial_report.get("ok")),
    }
    _write_json(trial_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
