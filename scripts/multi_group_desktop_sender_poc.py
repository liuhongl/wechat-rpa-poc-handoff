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

from app.member_assistant_poc import applescript_quote


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("each reply job JSONL row must be an object")
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_clipboard_applescript(
    *,
    app_name: str,
    chat_name: str,
    send: bool,
) -> str:
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
    return "\n".join(lines) + "\n"


def _run_osascript(script: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit("multi-group desktop sender POC currently supports macOS only")
    subprocess.run(["osascript"], input=script, text=True, check=True)


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
        _run_osascript(
            _build_clipboard_applescript(
                app_name=app_name,
                chat_name=chat_name,
                send=send,
            )
        )
    finally:
        subprocess.run(["pbcopy"], input=previous_clipboard, text=True, check=False)


def _plan_rows(
    jobs: list[dict[str, Any]],
    *,
    app_name: str,
    send: bool,
    will_run: bool,
    include_applescript: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        chat_name = str(job.get("chat_name") or "").strip()
        reply_content = str(job.get("reply_content") or "").strip()
        if not chat_name or not reply_content:
            continue

        row: dict[str, Any] = {
            "source_msgid": str(job.get("source_msgid") or ""),
            "roomid": str(job.get("roomid") or ""),
            "chat_name": chat_name,
            "reply_content": reply_content,
            "will_run": will_run,
            "send": send,
        }
        if include_applescript:
            row["applescript"] = _build_clipboard_applescript(
                app_name=app_name,
                chat_name=chat_name,
                send=send,
            )
        rows.append(row)
    return rows


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC: compose/send multi-group reply jobs in WeCom desktop. Defaults to plan-only."
    )
    parser.add_argument(
        "--reply-jobs-jsonl",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "multi_group_reply_jobs.jsonl",
    )
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--include-applescript", action="store_true")
    parser.add_argument("--run", action="store_true", help="Compose replies into WeCom desktop. Does not send unless --send is also set.")
    parser.add_argument("--send", action="store_true", help="Send composed replies. Implies --run.")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "member_assistant_poc" / "multi_group_desktop_send_plans.jsonl",
    )
    args = parser.parse_args()

    if args.send:
        args.run = True
    if args.max_jobs < 1:
        raise SystemExit("--max-jobs must be >= 1")

    jobs = _load_jsonl(args.reply_jobs_jsonl)[: args.max_jobs]
    rows = _plan_rows(
        jobs,
        app_name=args.app_name,
        send=args.send,
        will_run=args.run,
        include_applescript=args.include_applescript,
    )

    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    _write_jsonl(args.out, rows)

    if not rows:
        print("[multi-group-desktop-sender] no pending send plans", flush=True)
        return

    if args.run:
        for row in rows:
            _compose_with_clipboard(
                app_name=args.app_name,
                chat_name=str(row["chat_name"]),
                message=str(row["reply_content"]),
                send=args.send,
            )


if __name__ == "__main__":
    main()
