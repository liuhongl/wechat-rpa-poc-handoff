from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


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


def _heartbeat_age_seconds(heartbeat: dict[str, Any], *, now: str) -> int | None:
    captured_at = str(heartbeat.get("captured_at") or "")
    if not captured_at:
        return None
    delta = _parse_iso_datetime(now) - _parse_iso_datetime(captured_at)
    return int(delta.total_seconds())


def build_scan_health_summary(
    rows: list[dict[str, Any]],
    *,
    now: str,
    max_heartbeat_age_seconds: int,
) -> dict[str, Any]:
    row_types = Counter(str(row.get("type") or "") for row in rows)
    heartbeat_rows = [row for row in rows if row.get("type") == "scan_heartbeat"]
    preflight_rows = [row for row in rows if row.get("type") == "send_preflight"]
    last_heartbeat = heartbeat_rows[-1] if heartbeat_rows else None
    heartbeat_age = (
        _heartbeat_age_seconds(last_heartbeat, now=now)
        if last_heartbeat is not None
        else None
    )

    failures: list[str] = []
    if last_heartbeat is None:
        failures.append("missing_heartbeat")
    elif heartbeat_age is None:
        failures.append("missing_heartbeat_timestamp")
    elif heartbeat_age > max_heartbeat_age_seconds:
        failures.append("stale_heartbeat")

    preflight_status_counts = Counter(
        str(row.get("status") or "")
        for row in preflight_rows
        if str(row.get("status") or "")
    )

    return {
        "ok": not failures,
        "status": "ok" if not failures else "failed",
        "now": now,
        "total_rows": len(rows),
        "heartbeat_count": row_types["scan_heartbeat"],
        "last_heartbeat_at": str(last_heartbeat.get("captured_at") or "") if last_heartbeat else "",
        "last_heartbeat_age_seconds": heartbeat_age,
        "latest_snapshot_ref": str(last_heartbeat.get("snapshot_ref") or "") if last_heartbeat else "",
        "latest_send_plan_count": int(last_heartbeat.get("send_plan_count") or 0) if last_heartbeat else 0,
        "event_count": row_types["wecom_event"],
        "reply_job_count": row_types["reply_job"],
        "send_plan_count": row_types["send_plan"],
        "desktop_snapshot_count": row_types["desktop_snapshot"],
        "preflight_count": row_types["send_preflight"],
        "preflight_status_counts": dict(preflight_status_counts),
        "idle_heartbeat_count": sum(1 for row in heartbeat_rows if row.get("status") == "idle"),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: summarize no-message-audit desktop scan JSONL health."
    )
    parser.add_argument("--log-jsonl", type=Path, required=True)
    parser.add_argument("--now", default="")
    parser.add_argument("--max-heartbeat-age-seconds", type=int, default=60)
    args = parser.parse_args()

    if args.max_heartbeat_age_seconds < 0:
        raise SystemExit("--max-heartbeat-age-seconds must be >= 0")

    summary = build_scan_health_summary(
        _load_jsonl(args.log_jsonl),
        now=args.now or _now_iso(),
        max_heartbeat_age_seconds=args.max_heartbeat_age_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
