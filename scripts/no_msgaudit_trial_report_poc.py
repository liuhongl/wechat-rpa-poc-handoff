from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
READY_PREFLIGHT_STATUSES = {"ready_to_draft", "needs_operator_confirm", "ready_to_send"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _load_enabled_chat_names(path: Path) -> set[str]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError("group targets JSON must be a list")
    chat_names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("each group target must be an object")
        if not bool(item.get("enabled", True)):
            continue
        chat_name = str(item.get("chat_name") or "").strip()
        if chat_name:
            chat_names.add(chat_name)
    return chat_names


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _duration_seconds(heartbeat_rows: list[dict[str, Any]]) -> int:
    captured_values = [
        str(row.get("captured_at") or "")
        for row in heartbeat_rows
        if str(row.get("captured_at") or "")
    ]
    if len(captured_values) < 2:
        return 0
    delta = _parse_iso_datetime(captured_values[-1]) - _parse_iso_datetime(captured_values[0])
    return int(delta.total_seconds())


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(value for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


def _unknown_values(values: Iterable[str], allowed_values: set[str]) -> list[str]:
    return sorted({value for value in values if value and value not in allowed_values})


def _has_ready_preflight(
    send_plan: dict[str, Any],
    *,
    ready_preflight_rows: list[dict[str, Any]],
) -> bool:
    job_id = str(send_plan.get("job_id") or "")
    event_id = str(send_plan.get("event_id") or "")
    for row in ready_preflight_rows:
        if job_id and str(row.get("job_id") or "") == job_id:
            return True
        if event_id and str(row.get("event_id") or "") == event_id:
            return True
    return False


def build_trial_report(
    rows: list[dict[str, Any]],
    *,
    allowed_chat_names: set[str],
    min_duration_seconds: int,
    min_heartbeat_count: int,
) -> dict[str, Any]:
    row_types = Counter(str(row.get("type") or "") for row in rows)
    heartbeat_rows = [row for row in rows if row.get("type") == "scan_heartbeat"]
    event_rows = [row for row in rows if row.get("type") == "wecom_event"]
    send_plan_rows = [row for row in rows if row.get("type") == "send_plan"]
    preflight_rows = [row for row in rows if row.get("type") == "send_preflight"]
    snapshot_rows = [row for row in rows if row.get("type") == "desktop_snapshot"]
    ready_preflight_rows = [
        row for row in preflight_rows if str(row.get("status") or "") in READY_PREFLIGHT_STATUSES
    ]

    duplicate_event_ids = _duplicates(str(row.get("event_id") or "") for row in event_rows)
    duplicate_send_plan_event_ids = _duplicates(str(row.get("event_id") or "") for row in send_plan_rows)
    unknown_event_chats = _unknown_values(
        (str(row.get("chat_name") or "").strip() for row in event_rows),
        allowed_chat_names,
    )
    unknown_send_plan_chats = _unknown_values(
        (str(row.get("chat_name") or "").strip() for row in send_plan_rows),
        allowed_chat_names,
    )
    unknown_snapshot_chats = _unknown_values(
        (str(row.get("current_chat_name") or "").strip() for row in snapshot_rows),
        allowed_chat_names,
    )
    send_plans_without_ready_preflight = [
        str(row.get("job_id") or row.get("event_id") or "")
        for row in send_plan_rows
        if not _has_ready_preflight(row, ready_preflight_rows=ready_preflight_rows)
    ]
    send_plans_without_ready_preflight = sorted(
        {value for value in send_plans_without_ready_preflight if value}
    )

    duration = _duration_seconds(heartbeat_rows)
    failures: list[str] = []
    if not heartbeat_rows:
        failures.append("missing_heartbeat")
    if len(heartbeat_rows) < min_heartbeat_count:
        failures.append("insufficient_heartbeat_count")
    if duration < min_duration_seconds:
        failures.append("insufficient_duration_seconds")
    if duplicate_event_ids:
        failures.append("duplicate_event_id")
    if duplicate_send_plan_event_ids:
        failures.append("duplicate_send_plan_event_id")
    if unknown_event_chats:
        failures.append("unknown_event_chat")
    if unknown_send_plan_chats:
        failures.append("unknown_send_plan_chat")
    if unknown_snapshot_chats:
        failures.append("unknown_snapshot_chat")
    if send_plans_without_ready_preflight:
        failures.append("send_plan_without_ready_preflight")

    first_heartbeat = heartbeat_rows[0] if heartbeat_rows else {}
    last_heartbeat = heartbeat_rows[-1] if heartbeat_rows else {}
    return {
        "ok": not failures,
        "status": "accepted" if not failures else "rejected",
        "total_rows": len(rows),
        "duration_seconds": duration,
        "min_duration_seconds": min_duration_seconds,
        "heartbeat_count": row_types["scan_heartbeat"],
        "min_heartbeat_count": min_heartbeat_count,
        "first_heartbeat_at": str(first_heartbeat.get("captured_at") or ""),
        "last_heartbeat_at": str(last_heartbeat.get("captured_at") or ""),
        "event_count": row_types["wecom_event"],
        "send_plan_count": row_types["send_plan"],
        "preflight_count": row_types["send_preflight"],
        "ready_preflight_count": len(ready_preflight_rows),
        "blocked_preflight_count": sum(1 for row in preflight_rows if row.get("status") == "blocked"),
        "desktop_snapshot_count": row_types["desktop_snapshot"],
        "allowed_chat_names": sorted(allowed_chat_names),
        "duplicate_event_ids": duplicate_event_ids,
        "duplicate_send_plan_event_ids": duplicate_send_plan_event_ids,
        "unknown_event_chats": unknown_event_chats,
        "unknown_send_plan_chats": unknown_send_plan_chats,
        "unknown_snapshot_chats": unknown_snapshot_chats,
        "send_plans_without_ready_preflight": send_plans_without_ready_preflight,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: build an acceptance report for a no-message-audit desktop scan trial."
    )
    parser.add_argument("--log-jsonl", type=Path, required=True)
    parser.add_argument(
        "--group-targets-json",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "multi_group_targets.json",
    )
    parser.add_argument("--min-duration-seconds", type=int, default=0)
    parser.add_argument("--min-heartbeat-count", type=int, default=1)
    args = parser.parse_args()

    if args.min_duration_seconds < 0:
        raise SystemExit("--min-duration-seconds must be >= 0")
    if args.min_heartbeat_count < 1:
        raise SystemExit("--min-heartbeat-count must be >= 1")

    report = build_trial_report(
        _load_jsonl(args.log_jsonl),
        allowed_chat_names=_load_enabled_chat_names(args.group_targets_json),
        min_duration_seconds=args.min_duration_seconds,
        min_heartbeat_count=args.min_heartbeat_count,
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
