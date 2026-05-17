from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import (
    GroupReplyTarget,
    load_processed_keys,
    plan_multi_group_reply_jobs,
    reply_job_to_dict,
    resolve_assistant_names,
)
from app.no_msgaudit_desktop_agent import (
    WeComDesktopSnapshot,
    build_desktop_snapshot_from_accessibility_tree_text,
    build_desktop_snapshot_from_ui_text,
    build_wecom_events_from_ui_snapshot,
    preflight_report_to_dict,
    reply_job_to_send_plan,
    send_plan_to_dict,
    validate_send_preflight,
    wecom_event_to_dict,
    wecom_event_to_plain_text_record,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_group_targets(path: Path) -> list[GroupReplyTarget]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError("group targets JSON must be a list")

    targets: list[GroupReplyTarget] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("each group target must be an object")
        targets.append(
            GroupReplyTarget(
                roomid=str(item.get("roomid") or ""),
                chat_name=str(item.get("chat_name") or ""),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return targets


def _load_desktop_snapshot_json(path: Path) -> WeComDesktopSnapshot:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("desktop snapshot JSON must be an object")
    return WeComDesktopSnapshot(
        current_chat_name=str(payload.get("current_chat_name") or ""),
        selected_chat_name=str(payload.get("selected_chat_name") or ""),
        input_text=str(payload.get("input_text") or ""),
        app_online=bool(payload.get("app_online", True)),
        window_visible=bool(payload.get("window_visible", True)),
        captured_at=str(payload.get("captured_at") or ""),
        raw_snapshot_ref=str(payload.get("raw_snapshot_ref") or path),
    )


def _snapshot_to_dict(snapshot: WeComDesktopSnapshot) -> dict[str, Any]:
    return {
        "current_chat_name": snapshot.current_chat_name,
        "selected_chat_name": snapshot.selected_chat_name,
        "input_text": snapshot.input_text,
        "app_online": snapshot.app_online,
        "window_visible": snapshot.window_visible,
        "captured_at": snapshot.captured_at,
        "raw_snapshot_ref": snapshot.raw_snapshot_ref,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _snapshot_source_count(args: argparse.Namespace) -> int:
    return (
        len(args.desktop_snapshot_json)
        + len(args.desktop_snapshot_text_file)
        + len(args.desktop_accessibility_tree_text_file)
        + (1 if args.desktop_accessibility_tree_dir else 0)
    )


def _snapshot_source_kind_count(args: argparse.Namespace) -> int:
    return sum(
        [
            bool(args.desktop_snapshot_json),
            bool(args.desktop_snapshot_text_file),
            bool(args.desktop_accessibility_tree_text_file),
            bool(args.desktop_accessibility_tree_dir),
        ]
    )


def _accessibility_tree_path_from_dir(directory: Path, *, iteration: int) -> Path:
    paths = sorted(
        [path for path in directory.glob("*.txt") if path.is_file()],
        key=lambda path: path.name,
    )
    if not paths:
        raise SystemExit(f"no *.txt accessibility tree snapshots found in {directory}")
    index = min(iteration, len(paths) - 1)
    return paths[index]


def _load_snapshot_for_iteration(
    args: argparse.Namespace,
    *,
    targets: list[GroupReplyTarget],
    iteration: int,
    captured_at: str,
) -> WeComDesktopSnapshot:
    if args.desktop_snapshot_json:
        path = args.desktop_snapshot_json[iteration % len(args.desktop_snapshot_json)]
        snapshot = _load_desktop_snapshot_json(path)
        if snapshot.captured_at:
            return snapshot
        return WeComDesktopSnapshot(
            current_chat_name=snapshot.current_chat_name,
            selected_chat_name=snapshot.selected_chat_name,
            input_text=snapshot.input_text,
            app_online=snapshot.app_online,
            window_visible=snapshot.window_visible,
            captured_at=captured_at,
            raw_snapshot_ref=snapshot.raw_snapshot_ref,
        )
    if args.desktop_snapshot_text_file:
        path = args.desktop_snapshot_text_file[iteration % len(args.desktop_snapshot_text_file)]
        return build_desktop_snapshot_from_ui_text(
            path.read_text(encoding="utf-8"),
            captured_at=captured_at,
            raw_snapshot_ref=str(path),
        )
    if args.desktop_accessibility_tree_dir:
        path = _accessibility_tree_path_from_dir(
            args.desktop_accessibility_tree_dir,
            iteration=iteration,
        )
        return build_desktop_snapshot_from_accessibility_tree_text(
            path.read_text(encoding="utf-8"),
            group_targets=targets,
            captured_at=captured_at,
            raw_snapshot_ref=str(path),
        )
    path = args.desktop_accessibility_tree_text_file[iteration % len(args.desktop_accessibility_tree_text_file)]
    return build_desktop_snapshot_from_accessibility_tree_text(
        path.read_text(encoding="utf-8"),
        group_targets=targets,
        captured_at=captured_at,
        raw_snapshot_ref=str(path),
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC: continuously scan desktop snapshot files and emit dry-run preflight logs."
    )
    parser.add_argument(
        "--ui-text-file",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "wecom_gui_multi_group_snapshot.txt",
    )
    parser.add_argument(
        "--group-targets-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "multi_group_targets.json",
    )
    parser.add_argument("--assistant-name", action="append", default=[])
    parser.add_argument("--assistant-sender-id", action="append", default=[os.getenv("WECOM_ASSISTANT_SENDER_ID", "")])
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--human-userid", default=os.getenv("HUMAN_USERID", ""))
    parser.add_argument("--ignore-state", action="store_true")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=ROOT_DIR / "data" / "no_msgaudit_desktop_agent" / "processed_event_ids.json",
    )
    parser.add_argument("--desktop-snapshot-json", type=Path, action="append", default=[])
    parser.add_argument("--desktop-snapshot-text-file", type=Path, action="append", default=[])
    parser.add_argument("--desktop-accessibility-tree-text-file", type=Path, action="append", default=[])
    parser.add_argument("--desktop-accessibility-tree-dir", type=Path, default=None)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "no_msgaudit_desktop_agent" / "desktop_scan_log.jsonl",
    )
    args = parser.parse_args()

    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.interval_seconds < 0:
        raise SystemExit("--interval-seconds must be >= 0")
    if _snapshot_source_count(args) == 0:
        raise SystemExit("provide at least one desktop snapshot source")
    if _snapshot_source_kind_count(args) > 1:
        raise SystemExit(
            "use only one snapshot source kind: JSON files, structured text files, "
            "accessibility tree files, or accessibility tree directory"
        )

    assistant_names = resolve_assistant_names(
        args.assistant_name,
        env_value=os.getenv("WECOM_ASSISTANT_NAME", ""),
    )
    assistant_name = assistant_names[0]
    targets = _load_group_targets(args.group_targets_json)
    ui_text = args.ui_text_file.read_text(encoding="utf-8")
    base_detected_at = _now_iso()
    events = build_wecom_events_from_ui_snapshot(
        ui_text,
        group_targets=targets,
        assistant_name=assistant_name,
        detected_at=base_detected_at,
        raw_snapshot_ref=str(args.ui_text_file),
    )
    roomid_by_chat_name = {target.chat_name: target.roomid for target in targets}
    records = [
        wecom_event_to_plain_text_record(
            event,
            roomid_by_chat_name=roomid_by_chat_name,
        )
        for event in events
    ]
    processed = set() if args.ignore_state else load_processed_keys(args.state_file)
    jobs = plan_multi_group_reply_jobs(
        records,
        group_targets=targets,
        assistant_names=assistant_names,
        processed_keys=processed,
        app_name=args.app_name,
        human_userid=args.human_userid,
        assistant_sender_ids=args.assistant_sender_id,
    )
    send_plans = [reply_job_to_send_plan(job) for job in jobs]

    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append({"type": "wecom_event", **wecom_event_to_dict(event)})
    for job in jobs:
        rows.append({"type": "reply_job", **reply_job_to_dict(job)})
    for plan in send_plans:
        rows.append({"type": "send_plan", **send_plan_to_dict(plan)})

    for iteration in range(args.iterations):
        captured_at = _now_iso()
        snapshot = _load_snapshot_for_iteration(
            args,
            targets=targets,
            iteration=iteration,
            captured_at=captured_at,
        )
        heartbeat = {
            "type": "scan_heartbeat",
            "iteration": iteration + 1,
            "captured_at": snapshot.captured_at,
            "snapshot_ref": snapshot.raw_snapshot_ref,
            "send_plan_count": len(send_plans),
        }
        rows.append(heartbeat)
        rows.append({"type": "desktop_snapshot", "iteration": iteration + 1, **_snapshot_to_dict(snapshot)})
        for plan in send_plans:
            report = validate_send_preflight(
                plan,
                snapshot,
                processed_event_ids=processed,
            )
            rows.append(
                {
                    "type": "send_preflight",
                    "iteration": iteration + 1,
                    **preflight_report_to_dict(report),
                }
            )

        if args.interval_seconds and iteration < args.iterations - 1:
            time.sleep(args.interval_seconds)

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)


if __name__ == "__main__":
    main()
