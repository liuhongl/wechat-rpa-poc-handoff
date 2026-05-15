from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import build_at_member_applescript


def _run_applescript(script: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit("desktop @ POC currently supports macOS only")
    subprocess.run(["osascript"], input=script, text=True, check=True)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC that tries to create a real @ mention for a WeChat customer in a WeCom external group."
    )
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", ""))
    parser.add_argument("--member-name", default=os.getenv("WECOM_DESKTOP_AT_MEMBER_NAME", ""))
    parser.add_argument("--message", default="POC测试：账单还有3天到期，请确认是否收到真正的@提醒。")
    parser.add_argument("--run", action="store_true", help="Actually run osascript. Without this, only prints the script.")
    parser.add_argument("--send", action="store_true", help="Press Enter after composing the mention message.")
    parser.add_argument("--print-script", action="store_true", help="Print generated AppleScript before running.")
    args = parser.parse_args()

    if not args.chat_name:
        raise SystemExit("missing --chat-name or WECOM_DESKTOP_TARGET_CHAT_NAME")
    if not args.member_name:
        raise SystemExit("missing --member-name or WECOM_DESKTOP_AT_MEMBER_NAME")

    script = build_at_member_applescript(
        app_name=args.app_name,
        chat_name=args.chat_name,
        member_name=args.member_name,
        message=args.message,
        send=args.send,
    )

    if args.print_script or not args.run:
        print(script)

    if args.run:
        if args.send:
            print("[wecom-at] running and sending @ test message", flush=True)
        else:
            print("[wecom-at] running dry run: @ message will be composed but not sent", flush=True)
        _run_applescript(script)


if __name__ == "__main__":
    main()
