from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import (
    applescript_quote,
    extract_wecom_ui_mention_records,
    filter_unprocessed_records,
    load_processed_keys,
    plan_reply_actions,
    record_key,
    reply_action_to_dict,
    resolve_assistant_names,
    resolve_desktop_chat_name,
    save_processed_keys,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run_osascript(script: str) -> str:
    if sys.platform != "darwin":
        raise SystemExit("live desktop auto-reply POC currently supports macOS only")
    try:
        result = subprocess.run(
            ["osascript"],
            input=script,
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"osascript failed: {details}") from exc
    return result.stdout


def _read_wecom_ui_text(app_name: str) -> str:
    script = f"""
set targetApp to {applescript_quote(app_name)}
tell application targetApp to activate
delay 0.2
tell application "System Events"
  tell process targetApp
    set accText to ""
    repeat with itemRef in entire contents of window 1
      try
        set itemName to name of itemRef as text
        if itemName is not "" then set accText to accText & itemName & linefeed
      end try
    end repeat
    return accText
  end tell
end tell
"""
    return _run_osascript(script)


def _compose_with_clipboard(
    *,
    app_name: str,
    chat_name: str,
    message: str,
    send: bool,
) -> None:
    previous_clipboard = subprocess.run(
        ["pbpaste"],
        text=True,
        capture_output=True,
        check=False,
    ).stdout
    try:
        subprocess.run(["pbcopy"], input=message, text=True, check=True)
        lines = [
            f"set targetApp to {applescript_quote(app_name)}",
            f"set targetChat to {applescript_quote(chat_name)}",
            "tell application targetApp to activate",
            "delay 0.4",
            'tell application "System Events"',
            '  keystroke "f" using command down',
            "  delay 0.4",
            "  keystroke targetChat",
            "  delay 0.6",
            "  key code 36 -- open chat search result",
            "  delay 0.6",
            '  keystroke "v" using command down',
            "  delay 0.2",
        ]
        if send:
            lines.append("  key code 36 -- send")
        lines.append("end tell")
        script = "\n".join(lines) + "\n"
        _run_osascript(script)
    finally:
        subprocess.run(["pbcopy"], input=previous_clipboard, text=True, check=False)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC: read WeCom desktop UI mention rows and plan/compose an auto-reply without message-audit SDK."
    )
    parser.add_argument("--ui-text-file", type=Path, help="Optional captured WeCom UI text for dry-run/testing.")
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", ""))
    parser.add_argument("--roomid", default=os.getenv("WECOM_MSGAUDIT_TARGET_ROOMID", ""))
    parser.add_argument("--assistant-name", action="append", default=[])
    parser.add_argument("--assistant-sender-id", action="append", default=[os.getenv("WECOM_ASSISTANT_SENDER_ID", "")])
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--human-userid", default=os.getenv("HUMAN_USERID", ""))
    parser.add_argument("--ignore-state", action="store_true")
    parser.add_argument(
        "--mark-planned",
        action="store_true",
        help="Mark planned records as processed without desktop automation, for manually confirmed sends.",
    )
    parser.add_argument("--mark-processed", action="store_true")
    parser.add_argument("--run", action="store_true", help="Compose replies into WeCom desktop. Does not send unless --send is also set.")
    parser.add_argument("--send", action="store_true", help="Send composed replies. Implies --run and marks processed on success.")
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "data" / "member_assistant_poc" / "live_ui_reply_actions.jsonl")
    parser.add_argument("--state-file", type=Path, default=ROOT_DIR / "data" / "member_assistant_poc" / "live_ui_processed_msgids.json")
    args = parser.parse_args()

    if args.send:
        args.run = True
        args.mark_processed = True
    if args.mark_processed and not args.run:
        raise SystemExit("--mark-processed requires --run or --send")
    if args.max_actions < 1:
        raise SystemExit("--max-actions must be >= 1")

    chat_name = resolve_desktop_chat_name(args.chat_name, run=args.run)
    roomid = args.roomid or chat_name
    assistant_names = resolve_assistant_names(
        args.assistant_name,
        env_value=os.getenv("WECOM_ASSISTANT_NAME", ""),
    )

    if args.ui_text_file:
        ui_text = args.ui_text_file.read_text(encoding="utf-8")
    else:
        ui_text = _read_wecom_ui_text(args.app_name)

    records = extract_wecom_ui_mention_records(
        ui_text,
        target_chat_name=chat_name,
        roomid=roomid,
    )
    processed = set() if args.ignore_state else load_processed_keys(args.state_file)
    pending_records = filter_unprocessed_records(records, processed)
    actions = plan_reply_actions(
        pending_records,
        assistant_names=assistant_names,
        chat_name=chat_name,
        app_name=args.app_name,
        human_userid=args.human_userid,
        assistant_sender_ids=args.assistant_sender_id,
    )[: args.max_actions]
    rows = [reply_action_to_dict(action) for action in actions]

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)

    if not actions:
        print("[live-ui-auto-reply] no pending reply actions", flush=True)
        return

    if args.run:
        for action in actions:
            _compose_with_clipboard(
                app_name=args.app_name,
                chat_name=chat_name,
                message=action.reply_content,
                send=args.send,
            )
        if args.mark_processed:
            processed.update(record_key(action.record) for action in actions)
            save_processed_keys(args.state_file, processed)
    elif args.mark_planned:
        state_keys = load_processed_keys(args.state_file) if args.ignore_state else processed
        state_keys.update(record_key(action.record) for action in actions)
        save_processed_keys(args.state_file, state_keys)


if __name__ == "__main__":
    main()
