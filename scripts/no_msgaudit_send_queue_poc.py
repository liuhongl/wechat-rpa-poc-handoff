from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.no_msgaudit_desktop_agent import (
    WeComSendPlan,
    build_send_queue,
    queued_send_plan_to_dict,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _send_plan_from_row(row: dict[str, Any]) -> WeComSendPlan:
    return WeComSendPlan(
        job_id=str(row.get("job_id") or ""),
        event_id=str(row.get("event_id") or ""),
        chat_name=str(row.get("chat_name") or ""),
        reply_content=str(row.get("reply_content") or ""),
        mode=str(row.get("mode") or "draft"),
        requires_operator_confirm=bool(row.get("requires_operator_confirm", True)),
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_send_queue_rows(
    rows: list[dict[str, Any]],
    *,
    active_chat_locks: list[str],
) -> list[dict[str, Any]]:
    send_plans = [
        _send_plan_from_row(row)
        for row in rows
        if row.get("type") == "send_plan"
    ]
    queue_items = build_send_queue(
        send_plans,
        active_chat_locks=active_chat_locks,
    )
    queue_rows = [
        {"type": "send_queue_item", **queued_send_plan_to_dict(item)}
        for item in queue_items
    ]
    status_counts = Counter(row["dispatch_status"] for row in queue_rows)
    summary = {
        "type": "send_queue_summary",
        "queue_item_count": len(queue_rows),
        "ready_to_preflight_count": status_counts["ready_to_preflight"],
        "queued_after_chat_pending_count": status_counts["queued_after_chat_pending"],
        "waiting_for_chat_lock_count": status_counts["waiting_for_chat_lock"],
    }
    return [*queue_rows, summary]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: build a per-chat serialized send queue from no-message-audit scan logs."
    )
    parser.add_argument("--log-jsonl", type=Path, required=True)
    parser.add_argument("--active-chat-lock", action="append", default=[])
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "data" / "no_msgaudit_desktop_agent" / "send_queue.jsonl",
    )
    args = parser.parse_args()

    rows = build_send_queue_rows(
        _load_jsonl(args.log_jsonl),
        active_chat_locks=args.active_chat_lock,
    )
    _write_rows(args.out, rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
