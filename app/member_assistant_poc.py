from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


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


def applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
