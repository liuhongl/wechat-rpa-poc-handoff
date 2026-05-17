from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import applescript_quote


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _timestamp_for_filename(value: str) -> str:
    normalized = value.strip() or _now_iso()
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%Y%m%dT%H%M%S")
    except ValueError:
        return re.sub(r"[^0-9A-Za-z]+", "", normalized) or datetime.now().strftime("%Y%m%dT%H%M%S")


def _run_osascript(script: str) -> str:
    if sys.platform != "darwin":
        raise SystemExit("WeCom accessibility snapshot capture currently supports macOS only")
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


def _build_accessibility_tree_script(app_name: str) -> str:
    return f"""
set targetApp to {applescript_quote(app_name)}
tell application targetApp to activate
delay 0.2
tell application "System Events"
  tell process targetApp
    if not (exists window 1) then return ""
    set accText to ""
    repeat with itemRef in entire contents of window 1
      set lineText to ""
      try
        set itemRole to role description of itemRef as text
        if itemRole is not "" then set lineText to lineText & itemRole
      end try
      try
        set itemName to name of itemRef as text
        if itemName is not "" then set lineText to lineText & " " & itemName
      end try
      try
        set itemValue to value of itemRef as text
        if itemValue is not "" then set lineText to lineText & " " & itemValue
      end try
      if lineText is not "" then set accText to accText & lineText & linefeed
    end repeat
    return accText
  end tell
end tell
"""


def _read_wecom_accessibility_tree(app_name: str) -> str:
    tree_text = _run_osascript(_build_accessibility_tree_script(app_name))
    if not tree_text.strip():
        raise SystemExit(
            "no accessible UI tree from WeCom desktop; System Events could access the app "
            "but this WeCom view did not expose usable accessibility text"
        )
    return tree_text


def _write_snapshot(
    *,
    snapshot_dir: Path,
    prefix: str,
    captured_at: str,
    content: str,
    source: str,
) -> dict[str, object]:
    timestamp = _timestamp_for_filename(captured_at)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{prefix}-{timestamp}.txt"
    path.write_text(content, encoding="utf-8")
    return {
        "path": str(path),
        "captured_at": captured_at,
        "bytes": len(content.encode("utf-8")),
        "source": source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: capture WeCom accessibility text and write it into the no-message-audit snapshot spool."
    )
    parser.add_argument("--app-name", default="企业微信")
    parser.add_argument("--source-text-file", type=Path, default=None)
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT_DIR / "data" / "no_msgaudit_desktop_agent" / "accessibility_snapshots",
    )
    parser.add_argument("--prefix", default="wecom")
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()

    captured_at = args.captured_at or _now_iso()
    if args.source_text_file:
        content = args.source_text_file.read_text(encoding="utf-8")
        source = "source_text_file"
    else:
        content = _read_wecom_accessibility_tree(args.app_name)
        source = "osascript_system_events"

    payload = _write_snapshot(
        snapshot_dir=args.snapshot_dir,
        prefix=args.prefix,
        captured_at=captured_at,
        content=content,
        source=source,
    )
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
