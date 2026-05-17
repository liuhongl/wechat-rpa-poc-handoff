from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.member_assistant_poc import (
    GroupReplyTarget,
    MultiGroupReplyJob,
    PlainTextRecord,
    extract_wecom_ui_mention_records,
)


@dataclass(frozen=True)
class WeComEvent:
    event_id: str
    source: str
    chat_name: str
    sender_name: str
    content: str
    assistant_name: str
    detected_at: str
    confidence: float = 1.0
    raw_snapshot_ref: str = ""


@dataclass(frozen=True)
class WeComSendPlan:
    job_id: str
    event_id: str
    chat_name: str
    reply_content: str
    mode: str = "draft"
    requires_operator_confirm: bool = True


@dataclass(frozen=True)
class WeComDesktopSnapshot:
    current_chat_name: str
    selected_chat_name: str
    input_text: str = ""
    app_online: bool = True
    window_visible: bool = True
    captured_at: str = ""
    raw_snapshot_ref: str = ""


@dataclass(frozen=True)
class WeComSendPreflightReport:
    ok: bool
    status: str
    job_id: str
    event_id: str
    expected_chat_name: str
    verified_chat_name: str | None
    failures: list[str]
    warnings: list[str]
    can_send: bool


@dataclass(frozen=True)
class WeComSendResult:
    job_id: str
    chat_name: str
    status: str
    verified_chat_name: str | None = None
    sent_at: str | None = None
    error: str | None = None


def build_wecom_events_from_ui_snapshot(
    ui_text: str,
    *,
    group_targets: Iterable[GroupReplyTarget],
    assistant_name: str,
    detected_at: str,
    raw_snapshot_ref: str = "",
    source: str = "desktop_ui",
) -> list[WeComEvent]:
    events: list[WeComEvent] = []

    for target in group_targets:
        if not target.enabled or not target.chat_name.strip():
            continue

        records = extract_wecom_ui_mention_records(
            ui_text,
            target_chat_name=target.chat_name,
            roomid=target.roomid,
        )
        for record in records:
            events.append(
                WeComEvent(
                    event_id=record.msgid,
                    source=source,
                    chat_name=target.chat_name,
                    sender_name=record.sender,
                    content=record.content,
                    assistant_name=assistant_name,
                    detected_at=detected_at,
                    confidence=1.0,
                    raw_snapshot_ref=raw_snapshot_ref,
                )
            )

    return events


def wecom_event_to_plain_text_record(
    event: WeComEvent,
    *,
    roomid_by_chat_name: dict[str, str],
) -> PlainTextRecord:
    roomid = roomid_by_chat_name.get(event.chat_name, "")
    return PlainTextRecord(
        seq=None,
        msgid=event.event_id,
        action="send",
        sender=event.sender_name,
        roomid=roomid,
        msgtime=None,
        content=event.content,
    )


def reply_job_to_send_plan(
    job: MultiGroupReplyJob,
    *,
    mode: str = "draft",
) -> WeComSendPlan:
    requires_operator_confirm = mode != "auto_send"
    return WeComSendPlan(
        job_id=f"reply:{job.source_msgid}",
        event_id=job.source_msgid,
        chat_name=job.chat_name,
        reply_content=job.reply_content,
        mode=mode,
        requires_operator_confirm=requires_operator_confirm,
    )


def wecom_event_to_dict(event: WeComEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "source": event.source,
        "chat_name": event.chat_name,
        "sender_name": event.sender_name,
        "content": event.content,
        "assistant_name": event.assistant_name,
        "detected_at": event.detected_at,
        "confidence": round(event.confidence, 4),
        "raw_snapshot_ref": event.raw_snapshot_ref,
    }


def send_plan_to_dict(plan: WeComSendPlan) -> dict[str, Any]:
    return {
        "job_id": plan.job_id,
        "event_id": plan.event_id,
        "chat_name": plan.chat_name,
        "reply_content": plan.reply_content,
        "mode": plan.mode,
        "requires_operator_confirm": plan.requires_operator_confirm,
        "send": plan.mode == "auto_send",
    }


def validate_send_preflight(
    plan: WeComSendPlan,
    snapshot: WeComDesktopSnapshot,
    *,
    processed_event_ids: Iterable[str],
    require_empty_input: bool = True,
) -> WeComSendPreflightReport:
    failures: list[str] = []
    warnings: list[str] = []
    expected_chat_name = plan.chat_name.strip()
    current_chat_name = snapshot.current_chat_name.strip()
    selected_chat_name = snapshot.selected_chat_name.strip()
    processed = set(processed_event_ids)

    if not snapshot.app_online:
        failures.append("app_offline")
    if not snapshot.window_visible:
        failures.append("window_not_visible")
    if not expected_chat_name:
        failures.append("missing_chat_name")
    if current_chat_name != expected_chat_name:
        failures.append("current_chat_mismatch")
    if selected_chat_name != expected_chat_name:
        failures.append("selected_chat_mismatch")
    if require_empty_input and snapshot.input_text.strip():
        failures.append("input_not_empty")
    if plan.event_id in processed:
        failures.append("already_processed")
    if plan.mode not in {"draft", "confirm_send", "auto_send"}:
        failures.append("invalid_send_mode")

    ok = not failures
    can_send = ok and plan.mode == "auto_send"
    if not failures and plan.mode == "auto_send":
        status = "ready_to_send"
    elif not failures and plan.mode == "confirm_send":
        status = "needs_operator_confirm"
    elif not failures:
        status = "ready_to_draft"
    else:
        status = "blocked"

    if ok and plan.requires_operator_confirm and plan.mode == "auto_send":
        warnings.append("operator_confirm_flag_ignored_for_auto_send")

    return WeComSendPreflightReport(
        ok=ok,
        status=status,
        job_id=plan.job_id,
        event_id=plan.event_id,
        expected_chat_name=expected_chat_name,
        verified_chat_name=current_chat_name or None,
        failures=failures,
        warnings=warnings,
        can_send=can_send,
    )


def preflight_report_to_dict(report: WeComSendPreflightReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "status": report.status,
        "job_id": report.job_id,
        "event_id": report.event_id,
        "expected_chat_name": report.expected_chat_name,
        "verified_chat_name": report.verified_chat_name,
        "failures": report.failures,
        "warnings": report.warnings,
        "can_send": report.can_send,
    }
