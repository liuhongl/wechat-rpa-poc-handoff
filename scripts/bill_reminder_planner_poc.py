from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import (
    BillReminder,
    bill_reminder_action_to_dict,
    load_processed_keys,
    plan_bill_reminder_actions,
    save_processed_keys,
)


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("reminders"), list):
        return payload["reminders"]
    raise ValueError("bill reminder JSON must be a list or {reminders: [...]}")


def _load_reminders(path: Path) -> list[BillReminder]:
    reminders: list[BillReminder] = []
    for row in _load_json_rows(path):
        reminders.append(
            BillReminder(
                bill_id=str(row["bill_id"]),
                roomid=str(row["roomid"]),
                chat_name=str(row.get("chat_name") or os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME") or "模拟外部客户群"),
                member_name=str(row["member_name"]),
                due_date=date.fromisoformat(str(row["due_date"])),
                status=str(row.get("status") or "active"),
            )
        )
    return reminders


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Plan proactive bill reminders for WeCom external groups. Dry-run by default."
    )
    parser.add_argument(
        "--sample-bills-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "bill_reminders.json",
    )
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--remind-day", type=int, action="append", default=[3, 2, 1])
    parser.add_argument("--send", action="store_true", help="Generate AppleScript with the final send keystroke.")
    parser.add_argument("--include-applescript", action="store_true")
    parser.add_argument("--ignore-state", action="store_true")
    parser.add_argument("--mark-planned", action="store_true", help="Mark planned reminders as sent in the local state file.")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "bill_reminder_state.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "bill_reminder_actions.jsonl",
    )
    args = parser.parse_args()

    today = date.fromisoformat(args.today)
    reminders = _load_reminders(args.sample_bills_json)
    sent_keys = set() if args.ignore_state else load_processed_keys(args.state_file)
    actions = plan_bill_reminder_actions(
        reminders,
        today=today,
        sent_keys=sent_keys,
        remind_days=args.remind_day,
        app_name=args.app_name,
        send=args.send,
    )
    rows = [
        bill_reminder_action_to_dict(action, include_applescript=args.include_applescript)
        for action in actions
    ]

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)

    if args.mark_planned and actions:
        sent_keys.update(action.state_key for action in actions)
        save_processed_keys(args.state_file, sent_keys)

    if not actions:
        print("[bill-reminder] no pending reminder actions", flush=True)


if __name__ == "__main__":
    main()
