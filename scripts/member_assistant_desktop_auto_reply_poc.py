from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import (
    filter_unprocessed_records,
    extract_plain_text_records,
    load_processed_keys,
    plan_reply_actions,
    record_key,
    reply_action_to_dict,
    resolve_assistant_names,
    resolve_desktop_chat_name,
    save_processed_keys,
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


def _run_applescript(script: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit("desktop auto-reply POC currently supports macOS only")
    subprocess.run(["osascript"], input=script, text=True, check=True)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="End-to-end POC: simulated/decrypted message audit -> reply plan -> optional WeCom desktop compose/send."
    )
    parser.add_argument(
        "--sample-plaintext-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "msgaudit_plaintext_messages.json",
    )
    parser.add_argument("--target-roomid", default=os.getenv("WECOM_MSGAUDIT_TARGET_ROOMID", "wr_sample_target_room"))
    parser.add_argument("--assistant-name", action="append", default=[])
    parser.add_argument("--assistant-sender-id", action="append", default=[os.getenv("WECOM_ASSISTANT_SENDER_ID", "")])
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", ""))
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--human-userid", default=os.getenv("HUMAN_USERID", ""))
    parser.add_argument("--include-non-mentions", action="store_true")
    parser.add_argument("--recent-context-limit", type=int, default=3)
    parser.add_argument("--ignore-state", action="store_true", help="Do not skip records from the processed state file.")
    parser.add_argument("--mark-processed", action="store_true", help="Mark planned records as processed after a successful run.")
    parser.add_argument("--run", action="store_true", help="Run generated AppleScript to compose replies.")
    parser.add_argument("--send", action="store_true", help="Press Enter to send replies. Implies --run and marks processed on success.")
    parser.add_argument("--max-actions", type=int, default=1, help="Safety cap. Defaults to 1 action per run.")
    parser.add_argument("--include-applescript", action="store_true")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "processed_msgids.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "desktop_auto_reply_actions.jsonl",
    )
    args = parser.parse_args()
    assistant_names = resolve_assistant_names(
        args.assistant_name,
        env_value=os.getenv("WECOM_ASSISTANT_NAME", ""),
    )

    if args.send:
        args.run = True
        args.mark_processed = True
    if args.mark_processed and not args.run:
        raise SystemExit("--mark-processed requires --run or --send")
    if args.max_actions < 1:
        raise SystemExit("--max-actions must be >= 1")
    try:
        args.chat_name = resolve_desktop_chat_name(args.chat_name, run=args.run)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    messages = _load_messages(args.sample_plaintext_json)
    records = extract_plain_text_records(messages, target_roomid=args.target_roomid or None)
    processed = set() if args.ignore_state else load_processed_keys(args.state_file)
    pending_records = filter_unprocessed_records(records, processed)
    actions = plan_reply_actions(
        pending_records,
        assistant_names=assistant_names,
        chat_name=args.chat_name,
        app_name=args.app_name,
        require_mention=not args.include_non_mentions,
        send=args.send,
        human_userid=args.human_userid,
        assistant_sender_ids=args.assistant_sender_id,
        recent_context_limit=args.recent_context_limit,
    )[: args.max_actions]

    rows = [
        reply_action_to_dict(action, include_applescript=args.include_applescript)
        for action in actions
    ]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)

    if not actions:
        print("[member-assistant] no pending reply actions", flush=True)
        return

    if args.run:
        for action in actions:
            _run_applescript(action.applescript)
        if args.mark_processed:
            processed.update(record_key(action.record) for action in actions)
            save_processed_keys(args.state_file, processed)


if __name__ == "__main__":
    main()
