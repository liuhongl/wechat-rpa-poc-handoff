from __future__ import annotations

import json
from dataclasses import dataclass
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
) -> list[ReplyAction]:
    names = [name.strip() for name in assistant_names if name.strip()]
    actions: list[ReplyAction] = []

    for record in records:
        if require_mention and not _mentions_assistant(record.content, names):
            continue

        reply = _reply_for_record(record, human_userid=human_userid)
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
        "matched_question": action.matched_question,
        "score": round(action.score, 4),
        "handoff": action.handoff,
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


def _reply_for_record(record: PlainTextRecord, *, human_userid: str = "") -> BotReply:
    callback = {
        "msgtype": "text",
        "chatid": record.roomid,
        "from": {"userid": record.sender},
        "text": {"content": record.content},
    }
    return answer(callback, human_userid=human_userid)
