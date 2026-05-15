from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import build_desktop_preflight_report


def _command_ok(command: list[str]) -> bool:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _app_exists(app_name: str) -> bool | None:
    if sys.platform != "darwin":
        return None
    for app_dir in [Path("/Applications"), Path.home() / "Applications"]:
        if (app_dir / f"{app_name}.app").exists():
            return True
    if _command_ok(["mdfind", f"kMDItemKind == 'Application' && kMDItemFSName == '{app_name}.app'"]):
        result = subprocess.run(
            ["mdfind", f"kMDItemKind == 'Application' && kMDItemFSName == '{app_name}.app'"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())
    return None


def _osascript_available() -> bool:
    return _command_ok(["osascript", "-e", "return \"ok\""])


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Preflight check for the WeCom desktop automation POC."
    )
    parser.add_argument("--app-name", default=os.getenv("WECOM_DESKTOP_APP_NAME", "企业微信"))
    parser.add_argument("--chat-name", default=os.getenv("WECOM_DESKTOP_TARGET_CHAT_NAME", ""))
    parser.add_argument("--run", action="store_true", help="Report that the next step intends to run AppleScript.")
    parser.add_argument("--send", action="store_true", help="Report that the next step intends to send a message.")
    args = parser.parse_args()

    report = build_desktop_preflight_report(
        app_name=args.app_name,
        chat_name=args.chat_name,
        platform=sys.platform,
        run=args.run,
        send=args.send,
    )
    payload = asdict(report)
    payload["osascript_available"] = _osascript_available()
    payload["app_exists"] = _app_exists(args.app_name)
    payload["notes"] = [
        "This preflight does not open WeCom, search chats, type text, or send messages.",
        "Grant Accessibility permission to the terminal/Codex app before running --run scripts.",
    ]

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
