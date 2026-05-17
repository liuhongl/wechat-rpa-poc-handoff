from __future__ import annotations

import re
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
class WeComQueuedSendPlan:
    queue_id: str
    job_id: str
    event_id: str
    chat_name: str
    reply_content: str
    chat_queue_position: int
    dispatch_status: str
    blocked_by: list[str]


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


def build_wecom_events_from_accessibility_tree_text(
    tree_text: str,
    *,
    group_targets: Iterable[GroupReplyTarget],
    assistant_name: str,
    detected_at: str,
    raw_snapshot_ref: str = "",
    source: str = "desktop_accessibility_tree",
) -> list[WeComEvent]:
    targets = [
        target
        for target in group_targets
        if target.enabled and target.roomid.strip() and target.chat_name.strip()
    ]
    target_names = [target.chat_name for target in targets]
    current_chat_name = _find_current_chat_name_from_accessibility_tree(tree_text, target_names)
    target = next((item for item in targets if item.chat_name == current_chat_name), None)
    if target is None:
        return []

    events: list[WeComEvent] = []
    event_key_counts: dict[str, int] = {}
    for block in _iter_accessibility_row_blocks(tree_text):
        content_items = _message_contents_from_accessibility_block(block)
        if not content_items:
            continue
        sender_name = _sender_from_accessibility_message_block(
            block,
            current_chat_name=current_chat_name,
            assistant_name=assistant_name,
        )
        if not sender_name or sender_name == assistant_name:
            continue

        for content in content_items:
            if not _content_mentions_assistant(content, assistant_name):
                continue
            event_key = f"ax:{current_chat_name}:{sender_name}:{content}"
            occurrence = event_key_counts.get(event_key, 0) + 1
            event_key_counts[event_key] = occurrence
            event_id = f"{event_key}#{occurrence}"
            events.append(
                WeComEvent(
                    event_id=event_id,
                    source=source,
                    chat_name=current_chat_name,
                    sender_name=sender_name,
                    content=content,
                    assistant_name=assistant_name,
                    detected_at=detected_at,
                    confidence=0.85,
                    raw_snapshot_ref=raw_snapshot_ref,
                )
            )

    return events


def build_desktop_snapshot_from_ui_text(
    ui_text: str,
    *,
    captured_at: str,
    raw_snapshot_ref: str = "",
) -> WeComDesktopSnapshot:
    fields = _parse_key_value_lines(ui_text)
    return WeComDesktopSnapshot(
        current_chat_name=_first_field(
            fields,
            "current_chat_name",
            "当前群名",
            "顶部群名",
            "当前聊天",
        ),
        selected_chat_name=_first_field(
            fields,
            "selected_chat_name",
            "左侧选中会话",
            "选中会话",
        ),
        input_text=_first_field(
            fields,
            "input_text",
            "输入框",
            "草稿",
        ),
        app_online=_parse_bool(
            _first_field(
                fields,
                "app_online",
                "企业微信在线",
                default="true",
            )
        ),
        window_visible=_parse_bool(
            _first_field(
                fields,
                "window_visible",
                "窗口可见",
                default="true",
            )
        ),
        captured_at=captured_at,
        raw_snapshot_ref=raw_snapshot_ref,
    )


def build_desktop_snapshot_from_accessibility_tree_text(
    tree_text: str,
    *,
    group_targets: Iterable[GroupReplyTarget],
    captured_at: str,
    raw_snapshot_ref: str = "",
) -> WeComDesktopSnapshot:
    target_names = [
        target.chat_name.strip()
        for target in group_targets
        if target.enabled and target.chat_name.strip()
    ]
    current_chat_name = _find_current_chat_name_from_accessibility_tree(tree_text, target_names)
    selected_chat_name = _find_selected_chat_name_from_accessibility_tree(tree_text, target_names)
    input_text = _find_composer_input_text_from_accessibility_tree(tree_text)
    return WeComDesktopSnapshot(
        current_chat_name=current_chat_name,
        selected_chat_name=selected_chat_name,
        input_text=input_text,
        app_online=bool(tree_text.strip()),
        window_visible=bool(tree_text.strip()),
        captured_at=captured_at,
        raw_snapshot_ref=raw_snapshot_ref,
    )


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


def build_send_queue(
    send_plans: Iterable[WeComSendPlan],
    *,
    active_chat_locks: Iterable[str],
) -> list[WeComQueuedSendPlan]:
    locked_chats = {chat_name.strip() for chat_name in active_chat_locks if chat_name.strip()}
    chat_counts: dict[str, int] = {}
    queue: list[WeComQueuedSendPlan] = []
    for plan in send_plans:
        chat_name = plan.chat_name.strip()
        position = chat_counts.get(chat_name, 0) + 1
        chat_counts[chat_name] = position
        if chat_name in locked_chats:
            dispatch_status = "waiting_for_chat_lock"
            blocked_by = ["chat_lock_active"]
        elif position == 1:
            dispatch_status = "ready_to_preflight"
            blocked_by = []
        else:
            dispatch_status = "queued_after_chat_pending"
            blocked_by = ["same_chat_pending"]
        queue.append(
            WeComQueuedSendPlan(
                queue_id=f"queue:{chat_name}:{position}:{plan.job_id}",
                job_id=plan.job_id,
                event_id=plan.event_id,
                chat_name=plan.chat_name,
                reply_content=plan.reply_content,
                chat_queue_position=position,
                dispatch_status=dispatch_status,
                blocked_by=blocked_by,
            )
        )
    return queue


def queued_send_plan_to_dict(item: WeComQueuedSendPlan) -> dict[str, Any]:
    return {
        "queue_id": item.queue_id,
        "job_id": item.job_id,
        "event_id": item.event_id,
        "chat_name": item.chat_name,
        "reply_content": item.reply_content,
        "chat_queue_position": item.chat_queue_position,
        "dispatch_status": item.dispatch_status,
        "blocked_by": item.blocked_by,
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


def _parse_key_value_lines(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        separator = ":" if ":" in line else "：" if "：" in line else ""
        if not separator:
            continue
        key, value = line.split(separator, 1)
        fields[key.strip()] = value.strip()
    return fields


def _first_field(fields: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in fields:
            return fields[key]
    return default


def _parse_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "否", "不", "离线", "不可见"}


def _find_current_chat_name_from_accessibility_tree(text: str, target_names: list[str]) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "文本栏 (settable, string)" not in line and not line.startswith("AXTextField"):
            continue
        for target_name in target_names:
            if target_name in line:
                return target_name
    return ""


def _find_selected_chat_name_from_accessibility_tree(text: str, target_names: list[str]) -> str:
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if "row (selected)" not in raw_line and "AXRow (selected)" not in raw_line:
            continue
        block = "\n".join(lines[index : index + 12])
        for target_name in target_names:
            if target_name in block:
                return target_name
    return ""


def _find_composer_input_text_from_accessibility_tree(text: str) -> str:
    values: list[str] = []
    marker = "文本输入区 (settable, string)"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("The focused UI element"):
            continue
        if marker not in line and not line.startswith("AXTextArea"):
            continue
        if marker in line:
            _, value = line.split(marker, 1)
            values.append(value.strip())
        elif line == "AXTextArea":
            values.append("")
        else:
            values.append(line.removeprefix("AXTextArea").strip())
    if not values:
        return ""
    return values[-1]


def _iter_accessibility_row_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        is_row = line.startswith("AXRow") or re.match(r"^\d+\s+row\b", line) is not None
        if is_row:
            if current:
                blocks.append(current)
            current = [raw_line]
            continue
        if current:
            current.append(raw_line)
    if current:
        blocks.append(current)
    return blocks


def _message_contents_from_accessibility_block(block: list[str]) -> list[str]:
    contents: list[str] = []
    for raw_line in block:
        line = raw_line.strip()
        if line == "AXTextArea":
            continue
        if line.startswith("AXTextArea "):
            content = line.removeprefix("AXTextArea").strip()
            if content:
                contents.append(content)
    return contents


def _sender_from_accessibility_message_block(
    block: list[str],
    *,
    current_chat_name: str,
    assistant_name: str,
) -> str:
    candidates: list[str] = []
    for raw_line in block:
        line = raw_line.strip()
        if not line.startswith("AXStaticText "):
            continue
        value = line.removeprefix("AXStaticText").strip()
        if _is_sender_candidate(value, current_chat_name=current_chat_name):
            candidates.append(value)
    if not candidates:
        return ""
    if assistant_name in candidates:
        return assistant_name
    return candidates[-1]


def _is_sender_candidate(value: str, *, current_chat_name: str) -> bool:
    if not value or value == current_chat_name:
        return False
    if re.match(r"^(\d{1,2}:\d{2}|昨天\s+\d{1,2}:\d{2}|星期[一二三四五六日天])$", value):
        return False
    if value.startswith("群成员") or value in {"微信联系人", "@微信"}:
        return False
    if value.startswith("由企业微信用户创建"):
        return False
    return True


def _content_mentions_assistant(content: str, assistant_name: str) -> bool:
    normalized_content = content.replace("\u2005", " ").strip()
    normalized_name = assistant_name.strip()
    return bool(normalized_name and f"@{normalized_name}" in normalized_content)
