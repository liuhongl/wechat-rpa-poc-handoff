from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _next_manual_index(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("type") == "expected_event") + 1


def _expected_id_for_index(
    *,
    explicit_id: str,
    prefix: str,
    index: int,
    count: int,
    existing_rows: list[dict[str, Any]],
) -> str:
    if explicit_id and count == 1:
        return explicit_id
    if explicit_id and count > 1:
        return f"{explicit_id}-{index:03d}"
    if prefix:
        return f"{prefix}-{index:03d}"
    return f"manual-{_next_manual_index(existing_rows) + index - 1:03d}"


def build_expected_event_rows(
    *,
    existing_rows: list[dict[str, Any]],
    expected_id: str,
    expected_id_prefix: str,
    chat_name: str,
    sender_name: str,
    content_contains: str,
    sent_at: str,
    count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        rows.append(
            {
                "type": "expected_event",
                "expected_id": _expected_id_for_index(
                    explicit_id=expected_id,
                    prefix=expected_id_prefix,
                    index=index,
                    count=count,
                    existing_rows=existing_rows,
                ),
                "chat_name": chat_name,
                "sender_name": sender_name,
                "content_contains": content_contains,
                "sent_at": sent_at,
            }
        )
    return rows


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: append manually expected @ events for no-message-audit recall checks."
    )
    parser.add_argument("--expected-events-jsonl", type=Path, required=True)
    parser.add_argument("--expected-id", default="")
    parser.add_argument("--expected-id-prefix", default="")
    parser.add_argument("--chat-name", required=True)
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--content-contains", required=True)
    parser.add_argument("--sent-at", default="")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    existing_rows = _load_jsonl(args.expected_events_jsonl)
    rows = build_expected_event_rows(
        existing_rows=existing_rows,
        expected_id=args.expected_id.strip(),
        expected_id_prefix=args.expected_id_prefix.strip(),
        chat_name=args.chat_name.strip(),
        sender_name=args.sender_name.strip(),
        content_contains=args.content_contains.strip(),
        sent_at=args.sent_at.strip() or _now_iso(),
        count=args.count,
    )
    _append_rows(args.expected_events_jsonl, rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
