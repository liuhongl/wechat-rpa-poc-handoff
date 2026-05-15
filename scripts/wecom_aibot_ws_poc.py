from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from websockets.asyncio.client import connect

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.wecom_ws import (
    WECOM_AIBOT_WS_URL,
    build_ping,
    build_send_msg,
    build_subscribe,
    is_ok_response,
)


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _new_req_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


async def _send_json(websocket: Any, payload: dict[str, Any]) -> None:
    raw = _json_dumps(payload)
    print(f"> {raw}", flush=True)
    await websocket.send(raw)


async def _recv_json(websocket: Any) -> dict[str, Any]:
    message = await websocket.recv()
    print(f"< {message}", flush=True)
    return json.loads(message)


async def _wait_for_ok_response(websocket: Any, req_id: str) -> None:
    while True:
        payload = await _recv_json(websocket)
        if is_ok_response(payload, req_id):
            return
        if payload.get("headers", {}).get("req_id") == req_id:
            raise RuntimeError(_json_dumps(payload))


async def _heartbeat(websocket: Any, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await _send_json(websocket, build_ping(req_id=_new_req_id("ping")))


async def _run(args: argparse.Namespace) -> None:
    load_dotenv()

    bot_id = os.getenv("WECOM_AIBOT_BOT_ID", "")
    secret = os.getenv("WECOM_AIBOT_SECRET", "")
    if not bot_id or not secret:
        raise SystemExit(
            "missing WECOM_AIBOT_BOT_ID or WECOM_AIBOT_SECRET in environment"
        )

    async with connect(args.url, ping_interval=None) as websocket:
        subscribe_req_id = _new_req_id("subscribe")
        await _send_json(
            websocket,
            build_subscribe(
                bot_id=bot_id,
                secret=secret,
                req_id=subscribe_req_id,
            ),
        )
        await _wait_for_ok_response(websocket, subscribe_req_id)

        heartbeat_task = asyncio.create_task(_heartbeat(websocket, args.ping_interval))

        if args.send_chatid and args.send_content:
            send_req_id = _new_req_id("send")
            await _send_json(
                websocket,
                build_send_msg(
                    chatid=args.send_chatid,
                    content=args.send_content,
                    req_id=send_req_id,
                    chat_type=args.chat_type,
                ),
            )
            await _wait_for_ok_response(websocket, send_req_id)

        try:
            while True:
                await _recv_json(websocket)
        finally:
            heartbeat_task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC client for WeCom AI Bot WebSocket long connection."
    )
    parser.add_argument(
        "--url",
        default=WECOM_AIBOT_WS_URL,
        help="WeCom AI Bot WebSocket endpoint.",
    )
    parser.add_argument(
        "--send-chatid",
        help="Optional chatid/userid for one aibot_send_msg test after subscribe.",
    )
    parser.add_argument(
        "--send-content",
        help="Optional markdown content for one aibot_send_msg test after subscribe.",
    )
    parser.add_argument(
        "--chat-type",
        type=int,
        default=2,
        help="1 for single chat, 2 for group chat. Defaults to group chat.",
    )
    parser.add_argument(
        "--ping-interval",
        type=int,
        default=30,
        help="Business heartbeat interval in seconds. Defaults to 30.",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
