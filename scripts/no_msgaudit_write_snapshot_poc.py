from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _timestamp_for_filename(value: str) -> str:
    normalized = value.strip() or _now_iso()
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%Y%m%dT%H%M%S")
    except ValueError:
        return re.sub(r"[^0-9A-Za-z]+", "", normalized) or datetime.now().strftime("%Y%m%dT%H%M%S")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: write stdin accessibility-tree text into a timestamped snapshot file."
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path("data/no_msgaudit_desktop_agent/accessibility_snapshots"),
    )
    parser.add_argument("--prefix", default="wecom")
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()

    content = sys.stdin.read()
    captured_at = args.captured_at or _now_iso()
    timestamp = _timestamp_for_filename(captured_at)
    args.snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = args.snapshot_dir / f"{args.prefix}-{timestamp}.txt"
    path.write_text(content, encoding="utf-8")

    print(
        json.dumps(
            {
                "path": str(path),
                "captured_at": captured_at,
                "bytes": len(content.encode("utf-8")),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
