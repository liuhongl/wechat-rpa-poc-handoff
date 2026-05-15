from __future__ import annotations

from typing import Any


WECOM_AIBOT_WS_URL = "wss://openws.work.weixin.qq.com"


def build_subscribe(bot_id: str, secret: str, req_id: str) -> dict[str, Any]:
    return {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": req_id},
        "body": {
            "bot_id": bot_id,
            "secret": secret,
        },
    }


def build_send_msg(
    chatid: str,
    content: str,
    req_id: str,
    chat_type: int = 2,
) -> dict[str, Any]:
    return {
        "cmd": "aibot_send_msg",
        "headers": {"req_id": req_id},
        "body": {
            "chatid": chatid,
            "chat_type": chat_type,
            "msgtype": "markdown",
            "markdown": {"content": content},
        },
    }


def build_ping(req_id: str) -> dict[str, Any]:
    return {
        "cmd": "ping",
        "headers": {"req_id": req_id},
    }


def is_ok_response(payload: dict[str, Any], req_id: str) -> bool:
    return (
        payload.get("headers", {}).get("req_id") == req_id
        and payload.get("errcode") == 0
    )
