from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.bot_logic import answer
from app.wecom_crypto import WeComCrypto, WeComCryptoError

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CALLBACK_LOG = DATA_DIR / "callbacks.jsonl"
STATE_FILE = DATA_DIR / "state.json"

app = FastAPI(title="WeCom AI Bot POC")


def settings() -> dict[str, str]:
    return {
        "token": os.getenv("WECOM_AIBOT_TOKEN", ""),
        "encoding_aes_key": os.getenv("WECOM_AIBOT_ENCODING_AES_KEY", ""),
        "receive_id": os.getenv("WECOM_AIBOT_RECEIVE_ID", ""),
        "human_userid": os.getenv("HUMAN_USERID", ""),
    }


def crypto() -> WeComCrypto:
    cfg = settings()
    return WeComCrypto(
        token=cfg["token"],
        encoding_aes_key=cfg["encoding_aes_key"],
        receive_id=cfg["receive_id"],
    )


def append_log(record: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with CALLBACK_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_state(**updates: Any) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    state: dict[str, Any] = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def encrypted_json_response(payload: dict[str, Any], nonce: str) -> JSONResponse:
    encrypted = crypto().encrypt(json.dumps(payload, ensure_ascii=False), nonce=nonce)
    return JSONResponse(
        {
            "encrypt": encrypted.encrypt,
            "msgsignature": encrypted.msgsignature,
            "timestamp": encrypted.timestamp,
            "nonce": encrypted.nonce,
        }
    )


@app.get("/health")
def health() -> dict[str, Any]:
    cfg = settings()
    return {
        "ok": True,
        "configured": bool(cfg["token"] and cfg["encoding_aes_key"]),
    }


@app.get("/wecom/aibot")
def verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> Response:
    try:
        plain = crypto().verify_url(msg_signature, timestamp, nonce, echostr)
    except WeComCryptoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=plain, media_type="text/plain")


@app.post("/wecom/aibot")
async def receive_callback(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> Response:
    body = await request.json()
    encrypted = body.get("encrypt")
    if not encrypted:
        raise HTTPException(status_code=400, detail="missing encrypt")

    try:
        wx_crypto = crypto()
        wx_crypto.verify_signature(msg_signature, timestamp, nonce, encrypted)
        plaintext = wx_crypto.decrypt(encrypted)
    except WeComCryptoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    callback = json.loads(plaintext)
    append_log(callback)

    if callback.get("response_url"):
        save_state(
            last_response_url=callback["response_url"],
            last_chatid=callback.get("chatid"),
            last_chattype=callback.get("chattype"),
        )

    if callback.get("msgtype") == "event":
        return encrypted_json_response({}, nonce=nonce)

    bot_reply = answer(callback, human_userid=settings()["human_userid"])
    reply_payload = {
        "msgtype": "stream",
        "stream": {
            "id": callback.get("msgid", "poc-stream"),
            "finish": True,
            "content": (
                f"{bot_reply.content}\n\n"
                f"> POC匹配：{bot_reply.matched_question or '转人工'}，"
                f"置信度：{bot_reply.score:.2f}"
            ),
        },
    }
    return encrypted_json_response(reply_payload, nonce=nonce)


@app.get("/debug/last-callback")
def last_callback() -> dict[str, Any]:
    if not CALLBACK_LOG.exists():
        return {"found": False}
    lines = CALLBACK_LOG.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {"found": False}
    return {"found": True, "callback": json.loads(lines[-1])}


@app.post("/debug/send-last-response")
async def send_last_response(content: str = "这是一条POC主动回复测试消息") -> dict[str, Any]:
    state = load_state()
    response_url = state.get("last_response_url")
    if not response_url:
        raise HTTPException(status_code=400, detail="no response_url captured yet")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            response_url,
            json={"msgtype": "markdown", "markdown": {"content": content}},
        )
    return {"status_code": resp.status_code, "text": resp.text}
