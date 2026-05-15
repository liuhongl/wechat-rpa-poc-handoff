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

from app.member_assistant_poc import DesktopSendPlan, build_send_text_applescript


def _run_applescript(script: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit("desktop automation POC currently supports macOS only")
    subprocess.run(["osascript"], input=script, text=True, check=True)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC that locates a WeCom desktop chat and types a text message."
    )
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", ""))
    parser.add_argument("--message", default="POC测试：企业微信客户端自动化文本发送验证")
    parser.add_argument("--run", action="store_true", help="Actually run osascript. Without this, only prints the script.")
    parser.add_argument("--send", action="store_true", help="Press Enter after typing. Requires --run to take effect.")
    parser.add_argument("--print-script", action="store_true", help="Print generated AppleScript before running.")
    args = parser.parse_args()

    if not args.chat_name:
        raise SystemExit("missing --chat-name or WECOM_DESKTOP_TARGET_CHAT_NAME")

    plan = DesktopSendPlan(
        app_name=args.app_name,
        chat_name=args.chat_name,
        message=args.message,
        send=args.send,
    )
    script = build_send_text_applescript(plan)

    if args.print_script or not args.run:
        print(script)

    if args.run:
        if args.send:
            print("[wecom-desktop] running and sending message", flush=True)
        else:
            print("[wecom-desktop] running dry run: message will be typed but not sent", flush=True)
        _run_applescript(script)


if __name__ == "__main__":
    main()
