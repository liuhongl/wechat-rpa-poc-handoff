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
    build_wecom_events_from_accessibility_tree_text,
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


def _reset_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _record_output_row(rows: list[dict[str, Any]], row: dict[str, Any], *, out_path: Path) -> None:
    line = json.dumps(row, ensure_ascii=False)
    rows.append(row)
    print(line, flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


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


def _next_unseen_accessibility_tree_path_from_dir(directory: Path, consumed_paths: set[str]) -> Path | None:
    paths = sorted(
        [path for path in directory.glob("*.txt") if path.is_file()],
        key=lambda path: path.name,
    )
    for path in paths:
        if _snapshot_cursor_key(path) not in consumed_paths:
            return path
    return None


def _snapshot_cursor_key(path: Path) -> str:
    return str(path.resolve())


def _load_consumed_snapshot_paths(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        values = payload.get("consumed_snapshot_paths", [])
    elif isinstance(payload, list):
        values = payload
    else:
        raise ValueError("snapshot cursor must be a JSON object or list")
    if not isinstance(values, list):
        raise ValueError("snapshot cursor consumed_snapshot_paths must be a list")
    return {str(value) for value in values}


def _save_consumed_snapshot_paths(path: Path | None, consumed_paths: set[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"consumed_snapshot_paths": sorted(consumed_paths)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _accessibility_tree_path_for_iteration(args: argparse.Namespace, *, iteration: int) -> Path:
    if args.desktop_accessibility_tree_dir:
        return _accessibility_tree_path_from_dir(
            args.desktop_accessibility_tree_dir,
            iteration=iteration,
        )
    if args.desktop_accessibility_tree_text_file:
        return args.desktop_accessibility_tree_text_file[iteration % len(args.desktop_accessibility_tree_text_file)]
    raise SystemExit("--events-from-accessibility-tree requires an accessibility tree snapshot source")


def _load_accessibility_tree_snapshot_from_path(
    path: Path,
    *,
    targets: list[GroupReplyTarget],
    captured_at: str,
) -> WeComDesktopSnapshot:
    return build_desktop_snapshot_from_accessibility_tree_text(
        path.read_text(encoding="utf-8"),
        group_targets=targets,
        captured_at=captured_at,
        raw_snapshot_ref=str(path),
    )


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


def _build_jobs_and_send_plans(
    events: list[Any],
    *,
    targets: list[GroupReplyTarget],
    assistant_names: list[str],
    processed: set[str],
    roomid_by_chat_name: dict[str, str],
    app_name: str,
    human_userid: str,
    assistant_sender_ids: list[str],
) -> tuple[list[Any], list[Any]]:
    records = [
        wecom_event_to_plain_text_record(
            event,
            roomid_by_chat_name=roomid_by_chat_name,
        )
        for event in events
    ]
    jobs = plan_multi_group_reply_jobs(
        records,
        group_targets=targets,
        assistant_names=assistant_names,
        processed_keys=processed,
        app_name=app_name,
        human_userid=human_userid,
        assistant_sender_ids=assistant_sender_ids,
    )
    send_plans = [reply_job_to_send_plan(job) for job in jobs]
    return jobs, send_plans


def _filter_unseen_events(events: list[Any], seen_event_ids: set[str]) -> list[Any]:
    unseen_events: list[Any] = []
    for event in events:
        if event.event_id in seen_event_ids:
            continue
        unseen_events.append(event)
    return unseen_events


def _append_event_job_plan_rows(
    rows: list[dict[str, Any]],
    *,
    events: list[Any],
    jobs: list[Any],
    send_plans: list[Any],
    out_path: Path,
    iteration: int | None = None,
) -> None:
    iteration_payload = {"iteration": iteration} if iteration is not None else {}
    for event in events:
        _record_output_row(
            rows,
            {"type": "wecom_event", **iteration_payload, **wecom_event_to_dict(event)},
            out_path=out_path,
        )
    for job in jobs:
        _record_output_row(
            rows,
            {"type": "reply_job", **iteration_payload, **reply_job_to_dict(job)},
            out_path=out_path,
        )
    for plan in send_plans:
        _record_output_row(
            rows,
            {"type": "send_plan", **iteration_payload, **send_plan_to_dict(plan)},
            out_path=out_path,
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
    parser.add_argument("--events-from-accessibility-tree", action="store_true")
    parser.add_argument("--follow-snapshot-dir", action="store_true")
    parser.add_argument("--snapshot-cursor-file", type=Path, default=None)
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
    if args.events_from_accessibility_tree and not (
        args.desktop_accessibility_tree_text_file or args.desktop_accessibility_tree_dir
    ):
        raise SystemExit("--events-from-accessibility-tree requires an accessibility tree snapshot source")
    if args.follow_snapshot_dir and not args.desktop_accessibility_tree_dir:
        raise SystemExit("--follow-snapshot-dir requires --desktop-accessibility-tree-dir")
    if args.follow_snapshot_dir and not args.events_from_accessibility_tree:
        raise SystemExit("--follow-snapshot-dir requires --events-from-accessibility-tree")

    assistant_names = resolve_assistant_names(
        args.assistant_name,
        env_value=os.getenv("WECOM_ASSISTANT_NAME", ""),
    )
    assistant_name = assistant_names[0]
    targets = _load_group_targets(args.group_targets_json)
    base_detected_at = _now_iso()
    roomid_by_chat_name = {target.chat_name: target.roomid for target in targets}
    processed = set() if args.ignore_state else load_processed_keys(args.state_file)
    seen_event_ids_this_run: set[str] = set()
    consumed_snapshot_paths_this_run = _load_consumed_snapshot_paths(args.snapshot_cursor_file)

    rows: list[dict[str, Any]] = []
    _reset_jsonl(args.out)
    send_plans: list[Any] = []
    if not args.events_from_accessibility_tree:
        ui_text = args.ui_text_file.read_text(encoding="utf-8")
        events = build_wecom_events_from_ui_snapshot(
            ui_text,
            group_targets=targets,
            assistant_name=assistant_name,
            detected_at=base_detected_at,
            raw_snapshot_ref=str(args.ui_text_file),
        )
        jobs, send_plans = _build_jobs_and_send_plans(
            events,
            targets=targets,
            assistant_names=assistant_names,
            processed=processed,
            roomid_by_chat_name=roomid_by_chat_name,
            app_name=args.app_name,
            human_userid=args.human_userid,
            assistant_sender_ids=args.assistant_sender_id,
        )
        _append_event_job_plan_rows(
            rows,
            events=events,
            jobs=jobs,
            send_plans=send_plans,
            out_path=args.out,
        )

    for iteration in range(args.iterations):
        captured_at = _now_iso()
        follow_snapshot_path = None
        if args.follow_snapshot_dir:
            follow_snapshot_path = _next_unseen_accessibility_tree_path_from_dir(
                args.desktop_accessibility_tree_dir,
                consumed_snapshot_paths_this_run,
            )
            if follow_snapshot_path is None:
                _record_output_row(
                    rows,
                    {
                        "type": "scan_heartbeat",
                        "iteration": iteration + 1,
                        "captured_at": captured_at,
                        "snapshot_ref": "",
                        "send_plan_count": 0,
                        "status": "idle",
                        "reason": "no_new_snapshot",
                    },
                    out_path=args.out,
                )
                if args.interval_seconds and iteration < args.iterations - 1:
                    time.sleep(args.interval_seconds)
                continue
            consumed_snapshot_paths_this_run.add(_snapshot_cursor_key(follow_snapshot_path))
            _save_consumed_snapshot_paths(args.snapshot_cursor_file, consumed_snapshot_paths_this_run)

        if args.events_from_accessibility_tree:
            event_source_path = follow_snapshot_path or _accessibility_tree_path_for_iteration(args, iteration=iteration)
            events = build_wecom_events_from_accessibility_tree_text(
                event_source_path.read_text(encoding="utf-8"),
                group_targets=targets,
                assistant_name=assistant_name,
                detected_at=captured_at,
                raw_snapshot_ref=str(event_source_path),
            )
            events = _filter_unseen_events(events, seen_event_ids_this_run)
            jobs, send_plans = _build_jobs_and_send_plans(
                events,
                targets=targets,
                assistant_names=assistant_names,
                processed=processed,
                roomid_by_chat_name=roomid_by_chat_name,
                app_name=args.app_name,
                human_userid=args.human_userid,
                assistant_sender_ids=args.assistant_sender_id,
            )
            _append_event_job_plan_rows(
                rows,
                events=events,
                jobs=jobs,
                send_plans=send_plans,
                out_path=args.out,
                iteration=iteration + 1,
            )
            seen_event_ids_this_run.update(job.source_msgid for job in jobs)

        if follow_snapshot_path:
            snapshot = _load_accessibility_tree_snapshot_from_path(
                follow_snapshot_path,
                targets=targets,
                captured_at=captured_at,
            )
        else:
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
        _record_output_row(rows, heartbeat, out_path=args.out)
        _record_output_row(
            rows,
            {"type": "desktop_snapshot", "iteration": iteration + 1, **_snapshot_to_dict(snapshot)},
            out_path=args.out,
        )
        for plan in send_plans:
            report = validate_send_preflight(
                plan,
                snapshot,
                processed_event_ids=processed,
            )
            _record_output_row(
                rows,
                {
                    "type": "send_preflight",
                    "iteration": iteration + 1,
                    **preflight_report_to_dict(report),
                },
                out_path=args.out,
            )

        if args.interval_seconds and iteration < args.iterations - 1:
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
