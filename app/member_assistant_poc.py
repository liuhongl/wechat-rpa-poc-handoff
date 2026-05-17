from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.bot_logic import BotReply, answer


@dataclass(frozen=True)
class PlainTextRecord:
    seq: int | None
    msgid: str
    action: str
    sender: str
    roomid: str
    msgtime: int | None
    content: str


@dataclass(frozen=True)
class DesktopSendPlan:
    app_name: str
    chat_name: str
    message: str
    send: bool = False
    search_delay: float = 0.6
    compose_delay: float = 0.5
    mention_delay: float = 0.8


@dataclass(frozen=True)
class ReplyAction:
    record: PlainTextRecord
    reply_content: str
    matched_question: str | None
    score: float
    handoff: bool
    applescript: str
    question_content: str | None = None


@dataclass(frozen=True)
class GroupReplyTarget:
    roomid: str
    chat_name: str
    enabled: bool = True


@dataclass(frozen=True)
class MultiGroupReplyJob:
    roomid: str
    chat_name: str
    source_msgid: str
    sender: str
    content: str
    reply_content: str
    matched_question: str | None
    score: float
    handoff: bool
    question_content: str | None
    applescript: str


@dataclass(frozen=True)
class BillReminder:
    bill_id: str
    roomid: str
    chat_name: str
    member_name: str
    due_date: date
    status: str = "active"


@dataclass(frozen=True)
class BillReminderAction:
    reminder: BillReminder
    remind_date: date
    days_before: int
    state_key: str
    message: str
    applescript: str


@dataclass(frozen=True)
class DesktopPreflightReport:
    ok: bool
    platform: str
    app_name: str
    chat_name: str
    will_run: bool
    will_send: bool
    missing: list[str]
    warnings: list[str]


def applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def resolve_desktop_chat_name(
    chat_name: str,
    *,
    run: bool,
    fallback: str = "模拟外部客户群",
) -> str:
    normalized = chat_name.strip()
    if normalized:
        return normalized
    if run:
        raise ValueError("missing --chat-name or WECOM_DESKTOP_TARGET_CHAT_NAME")
    return fallback


def resolve_assistant_names(
    explicit_names: Iterable[str],
    *,
    env_value: str,
    fallback: str = "小助理",
) -> list[str]:
    names = [name.strip() for name in explicit_names if name.strip()]
    if names:
        return names
    names = [name.strip() for name in env_value.split(",") if name.strip()]
    if names:
        return names
    return [fallback]


def build_desktop_preflight_report(
    *,
    app_name: str,
    chat_name: str,
    platform: str,
    run: bool,
    send: bool,
) -> DesktopPreflightReport:
    missing: list[str] = []
    warnings: list[str] = []

    if not app_name.strip():
        missing.append("app_name")
    if not chat_name.strip():
        missing.append("chat_name")
    if platform != "darwin":
        missing.append("macos")
        warnings.append("desktop automation currently supports macOS only")

    will_run = run or send
    will_send = send
    if will_send and not will_run:
        warnings.append("--send implies --run")

    return DesktopPreflightReport(
        ok=not missing,
        platform=platform,
        app_name=app_name,
        chat_name=chat_name,
        will_run=will_run,
        will_send=will_send,
        missing=missing,
        warnings=warnings,
    )


def extract_plain_text_records(
    messages: Iterable[dict[str, Any]],
    *,
    target_roomid: str | None = None,
) -> list[PlainTextRecord]:
    records: list[PlainTextRecord] = []

    for message in messages:
        roomid = str(message.get("roomid") or "")
        if target_roomid and roomid != target_roomid:
            continue
        if message.get("msgtype") != "text":
            continue

        content = message.get("text", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            continue

        records.append(
            PlainTextRecord(
                seq=_optional_int(message.get("seq")),
                msgid=str(message.get("msgid") or ""),
                action=str(message.get("action") or ""),
                sender=str(message.get("from") or ""),
                roomid=roomid,
                msgtime=_optional_int(message.get("msgtime")),
                content=content,
            )
        )

    return records


def extract_wecom_ui_mention_records(
    ui_text: str,
    *,
    target_chat_name: str,
    roomid: str,
) -> list[PlainTextRecord]:
    records: list[PlainTextRecord] = []
    marker = "[有人@我]"

    for line in ui_text.splitlines():
        line = line.strip()
        if not line or target_chat_name not in line or marker not in line:
            continue

        _, after_marker = line.split(marker, 1)
        match = re.match(r"\s*(?P<sender>[^:：]+)[:：]\s*(?P<content>.+?)\s*$", after_marker)
        if not match:
            continue

        sender = match.group("sender").strip()
        content = match.group("content").strip()
        records.append(
            PlainTextRecord(
                seq=None,
                msgid=f"ui:{target_chat_name}:{sender}:{content}",
                action="send",
                sender=sender,
                roomid=roomid,
                msgtime=None,
                content=content,
            )
        )

    return records


def extract_wecom_ui_mention_records_for_targets(
    ui_text: str,
    group_targets: Iterable[GroupReplyTarget],
) -> list[PlainTextRecord]:
    records: list[PlainTextRecord] = []
    for target in group_targets:
        if not target.enabled or not target.roomid.strip() or not target.chat_name.strip():
            continue
        records.extend(
            extract_wecom_ui_mention_records(
                ui_text,
                target_chat_name=target.chat_name,
                roomid=target.roomid,
            )
        )
    return records


def record_key(record: PlainTextRecord) -> str:
    if record.msgid:
        return record.msgid
    return f"{record.roomid}:{record.seq}"


def filter_unprocessed_records(
    records: Iterable[PlainTextRecord],
    processed_keys: Iterable[str],
) -> list[PlainTextRecord]:
    processed = set(processed_keys)
    return [record for record in records if record_key(record) not in processed]


def load_processed_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = path.read_text(encoding="utf-8").strip()
    if not payload:
        return set()
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("processed state must be a JSON list")
    return {str(item) for item in data}


def save_processed_keys(path: Path, keys: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = sorted(set(keys))
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def plan_reply_actions(
    records: Iterable[PlainTextRecord],
    *,
    assistant_names: Iterable[str],
    chat_name: str,
    app_name: str = "企业微信",
    require_mention: bool = True,
    send: bool = False,
    human_userid: str = "",
    assistant_sender_ids: Iterable[str] = (),
    recent_context_limit: int = 3,
    recent_context_window_ms: int = 10 * 60 * 1000,
) -> list[ReplyAction]:
    names = [name.strip() for name in assistant_names if name.strip()]
    assistant_senders = {sender.strip() for sender in assistant_sender_ids if sender.strip()}
    actions: list[ReplyAction] = []
    history: dict[tuple[str, str], list[PlainTextRecord]] = {}

    for record in records:
        if record.sender in assistant_senders:
            continue

        history_key = (record.roomid, record.sender)
        prior_records = history.get(history_key, [])

        if require_mention and not _mentions_assistant(record.content, names):
            _append_history(history, history_key, record, recent_context_limit)
            continue

        question_content = _question_content_for_record(
            record,
            names,
            prior_records,
            recent_context_limit=recent_context_limit,
            recent_context_window_ms=recent_context_window_ms,
        )
        reply_record = PlainTextRecord(
            seq=record.seq,
            msgid=record.msgid,
            action=record.action,
            sender=record.sender,
            roomid=record.roomid,
            msgtime=record.msgtime,
            content=question_content,
        )
        reply = _reply_for_record(reply_record, human_userid=human_userid)
        script = build_send_text_applescript(
            DesktopSendPlan(
                app_name=app_name,
                chat_name=chat_name,
                message=reply.content,
                send=send,
            )
        )
        actions.append(
            ReplyAction(
                record=record,
                reply_content=reply.content,
                matched_question=reply.matched_question,
                score=reply.score,
                handoff=reply.handoff,
                applescript=script,
                question_content=question_content,
            )
        )
        _append_history(history, history_key, record, recent_context_limit)

    return actions


def plan_multi_group_reply_jobs(
    records: Iterable[PlainTextRecord],
    *,
    group_targets: Iterable[GroupReplyTarget],
    assistant_names: Iterable[str],
    processed_keys: Iterable[str] = (),
    app_name: str = "企业微信",
    require_mention: bool = True,
    send: bool = False,
    human_userid: str = "",
    assistant_sender_ids: Iterable[str] = (),
    recent_context_limit: int = 3,
    recent_context_window_ms: int = 10 * 60 * 1000,
) -> list[MultiGroupReplyJob]:
    targets_by_roomid = {
        target.roomid: target
        for target in group_targets
        if target.enabled and target.roomid.strip() and target.chat_name.strip()
    }
    processed = set(processed_keys)
    records_by_roomid: dict[str, list[PlainTextRecord]] = {}

    for record in records:
        if record.roomid not in targets_by_roomid:
            continue
        if record_key(record) in processed:
            continue
        records_by_roomid.setdefault(record.roomid, []).append(record)

    jobs: list[MultiGroupReplyJob] = []
    for roomid, room_records in records_by_roomid.items():
        target = targets_by_roomid[roomid]
        actions = plan_reply_actions(
            room_records,
            assistant_names=assistant_names,
            chat_name=target.chat_name,
            app_name=app_name,
            require_mention=require_mention,
            send=send,
            human_userid=human_userid,
            assistant_sender_ids=assistant_sender_ids,
            recent_context_limit=recent_context_limit,
            recent_context_window_ms=recent_context_window_ms,
        )
        for action in actions:
            jobs.append(
                MultiGroupReplyJob(
                    roomid=roomid,
                    chat_name=target.chat_name,
                    source_msgid=record_key(action.record),
                    sender=action.record.sender,
                    content=action.record.content,
                    reply_content=action.reply_content,
                    matched_question=action.matched_question,
                    score=action.score,
                    handoff=action.handoff,
                    question_content=action.question_content,
                    applescript=action.applescript,
                )
            )

    return jobs


def plan_bill_reminder_actions(
    reminders: Iterable[BillReminder],
    *,
    today: date,
    sent_keys: Iterable[str],
    remind_days: Iterable[int] = (3, 2, 1),
    app_name: str = "企业微信",
    send: bool = False,
) -> list[BillReminderAction]:
    already_sent = set(sent_keys)
    valid_days = set(remind_days)
    actions: list[BillReminderAction] = []

    for reminder in reminders:
        if reminder.status.lower() not in {"active", "unpaid", "pending"}:
            continue

        days_before = (reminder.due_date - today).days
        if days_before not in valid_days:
            continue

        state_key = f"{reminder.bill_id}:{today.isoformat()}:d-{days_before}"
        if state_key in already_sent:
            continue

        message = f"账单还有{days_before}天到期，请及时确认还款安排。如已处理请忽略。"
        applescript = build_at_member_applescript(
            app_name=app_name,
            chat_name=reminder.chat_name,
            member_name=reminder.member_name,
            message=message,
            send=send,
        )
        actions.append(
            BillReminderAction(
                reminder=reminder,
                remind_date=today,
                days_before=days_before,
                state_key=state_key,
                message=message,
                applescript=applescript,
            )
        )

    return actions


def build_send_text_applescript(plan: DesktopSendPlan) -> str:
    lines = _base_focus_chat_lines(plan)
    lines.extend(
        [
            f"set targetMessage to {applescript_quote(plan.message)}",
            "tell application \"System Events\"",
            "  keystroke targetMessage",
        ]
    )
    if plan.send:
        lines.append("  key code 36 -- send")
    lines.extend(["end tell", "return \"ok\""])
    return "\n".join(lines) + "\n"


def reply_action_to_dict(action: ReplyAction, *, include_applescript: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "seq": action.record.seq,
        "msgid": action.record.msgid,
        "sender": action.record.sender,
        "roomid": action.record.roomid,
        "content": action.record.content,
        "reply_content": action.reply_content,
        "question_content": action.question_content,
        "matched_question": action.matched_question,
        "score": round(action.score, 4),
        "handoff": action.handoff,
    }
    if include_applescript:
        payload["applescript"] = action.applescript
    return payload


def reply_job_to_dict(job: MultiGroupReplyJob, *, include_applescript: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "roomid": job.roomid,
        "chat_name": job.chat_name,
        "source_msgid": job.source_msgid,
        "sender": job.sender,
        "content": job.content,
        "reply_content": job.reply_content,
        "question_content": job.question_content,
        "matched_question": job.matched_question,
        "score": round(job.score, 4),
        "handoff": job.handoff,
    }
    if include_applescript:
        payload["applescript"] = job.applescript
    return payload


def bill_reminder_action_to_dict(
    action: BillReminderAction,
    *,
    include_applescript: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "bill_id": action.reminder.bill_id,
        "roomid": action.reminder.roomid,
        "chat_name": action.reminder.chat_name,
        "member_name": action.reminder.member_name,
        "due_date": action.reminder.due_date.isoformat(),
        "status": action.reminder.status,
        "remind_date": action.remind_date.isoformat(),
        "days_before": action.days_before,
        "state_key": action.state_key,
        "message": action.message,
    }
    if include_applescript:
        payload["applescript"] = action.applescript
    return payload


def build_at_member_applescript(
    *,
    app_name: str,
    chat_name: str,
    member_name: str,
    message: str,
    send: bool = False,
    search_delay: float = 0.6,
    compose_delay: float = 0.5,
    mention_delay: float = 0.8,
) -> str:
    plan = DesktopSendPlan(
        app_name=app_name,
        chat_name=chat_name,
        message=message,
        send=send,
        search_delay=search_delay,
        compose_delay=compose_delay,
        mention_delay=mention_delay,
    )
    lines = _base_focus_chat_lines(plan)
    lines.extend(
        [
            f"set mentionText to {applescript_quote('@' + member_name)}",
            f"set trailingMessage to {applescript_quote(' ' + message)}",
            "tell application \"System Events\"",
            "  keystroke mentionText",
            f"  delay {plan.mention_delay}",
            "  key code 36 -- select mention candidate",
            f"  delay {plan.compose_delay}",
            "  keystroke trailingMessage",
        ]
    )
    if send:
        lines.append("  key code 36 -- send")
    lines.extend(["end tell", "return \"ok\""])
    return "\n".join(lines) + "\n"


def _base_focus_chat_lines(plan: DesktopSendPlan) -> list[str]:
    return [
        f"set targetApp to {applescript_quote(plan.app_name)}",
        f"set targetChat to {applescript_quote(plan.chat_name)}",
        f"set shouldSend to {'true' if plan.send else 'false'}",
        "tell application targetApp to activate",
        f"delay {plan.search_delay}",
        "tell application \"System Events\"",
        "  keystroke \"f\" using command down",
        f"  delay {plan.compose_delay}",
        "  keystroke targetChat",
        f"  delay {plan.search_delay}",
        "  key code 36 -- open chat search result",
        f"  delay {plan.search_delay}",
        "end tell",
    ]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mentions_assistant(content: str, assistant_names: list[str]) -> bool:
    if not assistant_names:
        return True
    normalized = content.replace(" ", "")
    return any(f"@{name}" in normalized for name in assistant_names)


def _strip_assistant_mentions(content: str, assistant_names: list[str]) -> str:
    cleaned = content
    for name in assistant_names:
        cleaned = cleaned.replace(f"@{name}", "")
    return " ".join(cleaned.split())


def _append_history(
    history: dict[tuple[str, str], list[PlainTextRecord]],
    key: tuple[str, str],
    record: PlainTextRecord,
    limit: int,
) -> None:
    rows = history.setdefault(key, [])
    rows.append(record)
    if len(rows) > limit:
        del rows[: len(rows) - limit]


def _question_content_for_record(
    record: PlainTextRecord,
    assistant_names: list[str],
    prior_records: list[PlainTextRecord],
    *,
    recent_context_limit: int,
    recent_context_window_ms: int,
) -> str:
    current_question = _strip_assistant_mentions(record.content, assistant_names)
    if current_question:
        return current_question

    if record.msgtime is None:
        candidates = prior_records[-recent_context_limit:]
    else:
        candidates = [
            prior
            for prior in prior_records[-recent_context_limit:]
            if prior.msgtime is None or 0 <= record.msgtime - prior.msgtime <= recent_context_window_ms
        ]
    context = [prior.content.strip() for prior in candidates if prior.content.strip()]
    return "\n".join(context) or record.content


def _reply_for_record(record: PlainTextRecord, *, human_userid: str = "") -> BotReply:
    callback = {
        "msgtype": "text",
        "chatid": record.roomid,
        "from": {"userid": record.sender},
        "text": {"content": record.content},
    }
    return answer(callback, human_userid=human_userid)
