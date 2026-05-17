from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def _matches_expected_event(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    expected_chat = str(expected.get("chat_name") or "").strip()
    expected_sender = str(expected.get("sender_name") or "").strip()
    expected_content = str(expected.get("content_contains") or expected.get("content") or "").strip()
    actual_chat = str(actual.get("chat_name") or "").strip()
    actual_sender = str(actual.get("sender_name") or "").strip()
    actual_content = str(actual.get("content") or "").strip()

    if expected_chat and expected_chat != actual_chat:
        return False
    if expected_sender and expected_sender != actual_sender:
        return False
    if expected_content and expected_content not in actual_content:
        return False
    return True


def build_event_recall_report(
    *,
    expected_rows: list[dict[str, Any]],
    scan_rows: list[dict[str, Any]],
    min_capture_rate: float,
) -> dict[str, Any]:
    expected_events = [row for row in expected_rows if row.get("type") == "expected_event"]
    actual_events = [row for row in scan_rows if row.get("type") == "wecom_event"]
    used_actual_indexes: set[int] = set()
    matched: list[dict[str, str]] = []
    missing: list[dict[str, Any]] = []

    for expected in expected_events:
        match_index = None
        for index, actual in enumerate(actual_events):
            if index in used_actual_indexes:
                continue
            if _matches_expected_event(expected, actual):
                match_index = index
                break
        if match_index is None:
            missing.append(expected)
            continue
        used_actual_indexes.add(match_index)
        matched.append(
            {
                "expected_id": str(expected.get("expected_id") or ""),
                "event_id": str(actual_events[match_index].get("event_id") or ""),
            }
        )

    expected_count = len(expected_events)
    captured_count = len(matched)
    capture_rate = 1.0 if expected_count == 0 else captured_count / expected_count
    ok = capture_rate >= min_capture_rate and not missing
    return {
        "ok": ok,
        "status": "accepted" if ok else "rejected",
        "expected_event_count": expected_count,
        "actual_event_count": len(actual_events),
        "captured_expected_count": captured_count,
        "missing_expected_count": len(missing),
        "capture_rate": round(capture_rate, 4),
        "min_capture_rate": min_capture_rate,
        "matched_events": matched,
        "missing_expected_events": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: compare manually expected @ events with captured no-message-audit wecom_event rows."
    )
    parser.add_argument("--expected-events-jsonl", type=Path, required=True)
    parser.add_argument("--scan-log-jsonl", type=Path, required=True)
    parser.add_argument("--min-capture-rate", type=float, default=1.0)
    args = parser.parse_args()

    if args.min_capture_rate < 0 or args.min_capture_rate > 1:
        raise SystemExit("--min-capture-rate must be between 0 and 1")

    report = build_event_recall_report(
        expected_rows=_load_jsonl(args.expected_events_jsonl),
        scan_rows=_load_jsonl(args.scan_log_jsonl),
        min_capture_rate=args.min_capture_rate,
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
