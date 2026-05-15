from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.member_assistant_poc import extract_plain_text_records


class Slice(ctypes.Structure):
    _fields_ = [("buf", ctypes.c_void_p), ("len", ctypes.c_int)]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_records(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")


def _print_records(records: list[Any]) -> None:
    for record in records:
        print(json.dumps(record.__dict__, ensure_ascii=False), flush=True)


def _load_private_key(path: Path) -> RSA.RsaKey:
    return RSA.import_key(path.read_bytes())


class MsgAuditSdk:
    def __init__(self, lib_path: Path, corp_id: str, secret: str) -> None:
        self.lib = ctypes.cdll.LoadLibrary(str(lib_path))
        self.sdk = self.lib.NewSdk()

        self.lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.lib.Init.restype = ctypes.c_int
        self.lib.GetChatData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulonglong,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(Slice),
        ]
        self.lib.GetChatData.restype = ctypes.c_int
        self.lib.DecryptData.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(Slice),
        ]
        self.lib.DecryptData.restype = ctypes.c_int
        self.lib.NewSlice.restype = ctypes.POINTER(Slice)
        self.lib.FreeSlice.argtypes = [ctypes.POINTER(Slice)]

        init_ret = self.lib.Init(
            self.sdk,
            corp_id.encode("utf-8"),
            secret.encode("utf-8"),
        )
        if init_ret != 0:
            raise RuntimeError(f"Init failed: {init_ret}")

    def get_chat_data(
        self,
        *,
        seq: int,
        limit: int,
        timeout: int,
        proxy: str = "",
        passwd: str = "",
    ) -> dict[str, Any]:
        output = self.lib.NewSlice()
        try:
            ret = self.lib.GetChatData(
                self.sdk,
                ctypes.c_ulonglong(seq),
                ctypes.c_uint(limit),
                proxy.encode("utf-8"),
                passwd.encode("utf-8"),
                timeout,
                output,
            )
            if ret != 0:
                raise RuntimeError(f"GetChatData failed: {ret}")
            raw = ctypes.string_at(output.contents.buf, output.contents.len)
            return json.loads(raw.decode("utf-8"))
        finally:
            self.lib.FreeSlice(output)

    def decrypt_chat_msg(self, encrypt_key: bytes, encrypt_msg: str) -> dict[str, Any]:
        output = self.lib.NewSlice()
        try:
            ret = self.lib.DecryptData(
                encrypt_key,
                encrypt_msg.encode("utf-8"),
                output,
            )
            if ret != 0:
                raise RuntimeError(f"DecryptData failed: {ret}")
            raw = ctypes.string_at(output.contents.buf, output.contents.len)
            return json.loads(raw.decode("utf-8"))
        finally:
            self.lib.FreeSlice(output)


def _decrypt_random_key(private_key: RSA.RsaKey, encrypted_random_key: str) -> bytes:
    cipher = PKCS1_v1_5.new(private_key)
    sentinel = b""
    decrypted = cipher.decrypt(base64.b64decode(encrypted_random_key), sentinel)
    if not decrypted:
        raise RuntimeError("failed to decrypt encrypt_random_key with private key")
    return decrypted


def _messages_from_sample(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        return payload["messages"]
    if isinstance(payload, dict) and payload.get("msgtype"):
        return [payload]
    raise ValueError("sample plaintext JSON must be a message object, a list, or {messages: [...]}")


def _messages_from_sdk(args: argparse.Namespace) -> list[dict[str, Any]]:
    sdk = MsgAuditSdk(args.sdk_lib, args.corp_id, args.secret)
    private_key = _load_private_key(args.private_key)
    payload = sdk.get_chat_data(seq=args.seq, limit=args.limit, timeout=args.timeout)
    encrypted_items = payload.get("chatdata") or []

    messages: list[dict[str, Any]] = []
    for item in encrypted_items:
        encrypt_key = _decrypt_random_key(private_key, item["encrypt_random_key"])
        messages.append(sdk.decrypt_chat_msg(encrypt_key, item["encrypt_chat_msg"]))
    return messages


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="POC reader for WeCom message audit records in an external customer group."
    )
    parser.add_argument("--sample-plaintext-json", type=Path, help="Parse already-decrypted sample JSON instead of calling the SDK.")
    parser.add_argument("--sdk-lib", type=Path, default=os.getenv("WECOM_MSGAUDIT_SDK_LIB_PATH"))
    parser.add_argument("--corp-id", default=os.getenv("WECOM_CORP_ID", ""))
    parser.add_argument("--secret", default=os.getenv("WECOM_MSGAUDIT_SECRET", ""))
    parser.add_argument("--private-key", type=Path, default=os.getenv("WECOM_MSGAUDIT_PRIVATE_KEY_PATH"))
    parser.add_argument("--target-roomid", default=os.getenv("WECOM_MSGAUDIT_TARGET_ROOMID", ""))
    parser.add_argument("--seq", type=int, default=int(os.getenv("WECOM_MSGAUDIT_START_SEQ", "0")))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "data" / "member_assistant_poc" / "msgaudit_records.jsonl")
    args = parser.parse_args()
    if args.sdk_lib and not isinstance(args.sdk_lib, Path):
        args.sdk_lib = Path(args.sdk_lib)
    if args.private_key and not isinstance(args.private_key, Path):
        args.private_key = Path(args.private_key)

    if args.sample_plaintext_json:
        messages = _messages_from_sample(args.sample_plaintext_json)
    else:
        missing = [
            name
            for name, value in [
                ("--sdk-lib/WECOM_MSGAUDIT_SDK_LIB_PATH", args.sdk_lib),
                ("--corp-id/WECOM_CORP_ID", args.corp_id),
                ("--secret/WECOM_MSGAUDIT_SECRET", args.secret),
                ("--private-key/WECOM_MSGAUDIT_PRIVATE_KEY_PATH", args.private_key),
            ]
            if not value
        ]
        if missing:
            raise SystemExit("missing required message-audit config: " + ", ".join(missing))
        messages = _messages_from_sdk(args)

    records = extract_plain_text_records(
        messages,
        target_roomid=args.target_roomid or None,
    )
    _print_records(records)
    _write_records(args.out, records)


if __name__ == "__main__":
    main()
