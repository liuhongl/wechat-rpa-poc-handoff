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
    extract_plain_text_records,
    plan_reply_actions,
    reply_action_to_dict,
)


def _load_messages(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        return payload["messages"]
    raise ValueError("sample plaintext JSON must be a list or {messages: [...]}")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Plan member-assistant replies from simulated/decrypted WeCom message-audit records."
    )
    parser.add_argument(
        "--sample-plaintext-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "msgaudit_plaintext_messages.json",
        help="Already-decrypted message audit plaintext JSON.",
    )
    parser.add_argument("--target-roomid", default=os.getenv("WECOM_MSGAUDIT_TARGET_ROOMID", "wr_sample_target_room"))
    parser.add_argument("--assistant-name", action="append", default=["小助理"], help="Assistant name that must be @ mentioned. Can be repeated.")
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", "模拟外部客户群"))
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--human-userid", default=os.getenv("HUMAN_USERID", ""))
    parser.add_argument("--include-non-mentions", action="store_true", help="Plan replies for all text records, not only @assistant messages.")
    parser.add_argument("--include-applescript", action="store_true", help="Include generated AppleScript in JSON output.")
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "data" / "member_assistant_poc" / "reply_actions.jsonl")
    args = parser.parse_args()

    messages = _load_messages(args.sample_plaintext_json)
    records = extract_plain_text_records(
        messages,
        target_roomid=args.target_roomid or None,
    )
    actions = plan_reply_actions(
        records,
        assistant_names=args.assistant_name,
        chat_name=args.chat_name,
        app_name=args.app_name,
        require_mention=not args.include_non_mentions,
        human_userid=args.human_userid,
    )
    rows = [reply_action_to_dict(action, include_applescript=args.include_applescript) for action in actions]

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)


if __name__ == "__main__":
    main()
