from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import (
    GroupReplyTarget,
    extract_wecom_ui_mention_records_for_targets,
    load_processed_keys,
    plan_multi_group_reply_jobs,
    reply_job_to_dict,
    resolve_assistant_names,
    save_processed_keys,
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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC: plan replies from a WeCom GUI conversation-list snapshot, without message-audit SDK."
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
    parser.add_argument("--mark-planned", action="store_true")
    parser.add_argument("--include-applescript", action="store_true")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "gui_snapshot_processed_msgids.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "gui_snapshot_reply_jobs.jsonl",
    )
    args = parser.parse_args()

    assistant_names = resolve_assistant_names(
        args.assistant_name,
        env_value=os.getenv("WECOM_ASSISTANT_NAME", ""),
    )
    targets = _load_group_targets(args.group_targets_json)
    ui_text = args.ui_text_file.read_text(encoding="utf-8")
    records = extract_wecom_ui_mention_records_for_targets(ui_text, targets)
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
    rows = [reply_job_to_dict(job, include_applescript=args.include_applescript) for job in jobs]

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)

    if args.mark_planned:
        processed.update(job.source_msgid for job in jobs)
        save_processed_keys(args.state_file, processed)

    if not jobs:
        print("[gui-snapshot-reply] no pending reply jobs", flush=True)


if __name__ == "__main__":
    main()
