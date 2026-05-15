import base64
import hashlib
import secrets
import struct
import time
from dataclasses import dataclass

from Crypto.Cipher import AES


class WeComCryptoError(Exception):
    pass


def _pkcs7_pad(data: bytes, block_size: int = 32) -> bytes:
    amount = block_size - (len(data) % block_size)
    return data + bytes([amount]) * amount


def _pkcs7_unpad(data: bytes, block_size: int = 32) -> bytes:
    if not data:
        raise WeComCryptoError("empty plaintext")
    amount = data[-1]
    if amount < 1 or amount > block_size:
        raise WeComCryptoError("invalid padding")
    if data[-amount:] != bytes([amount]) * amount:
        raise WeComCryptoError("invalid padding bytes")
    return data[:-amount]


def make_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce, encrypted]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class EncryptedMessage:
    encrypt: str
    msgsignature: str
    timestamp: int
    nonce: str


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str = ""):
        if not token:
            raise WeComCryptoError("WECOM_AIBOT_TOKEN is required")
        if not encoding_aes_key:
            raise WeComCryptoError("WECOM_AIBOT_ENCODING_AES_KEY is required")

        padded_key = encoding_aes_key + "="
        try:
            aes_key = base64.b64decode(padded_key)
        except Exception as exc:
            raise WeComCryptoError("invalid EncodingAESKey") from exc

        if len(aes_key) != 32:
            raise WeComCryptoError("EncodingAESKey must decode to 32 bytes")

        self.token = token
        self.aes_key = aes_key
        self.receive_id = receive_id or ""

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypted: str
    ) -> None:
        expected = make_signature(self.token, timestamp, nonce, encrypted)
        if expected != msg_signature:
            raise WeComCryptoError("invalid msg_signature")

    def verify_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> str:
        self.verify_signature(msg_signature, timestamp, nonce, echostr)
        return self.decrypt(echostr)

    def decrypt(self, encrypted: str) -> str:
        try:
            ciphertext = base64.b64decode(encrypted)
            cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
            plaintext = _pkcs7_unpad(cipher.decrypt(ciphertext))
        except Exception as exc:
            if isinstance(exc, WeComCryptoError):
                raise
            raise WeComCryptoError("failed to decrypt message") from exc

        if len(plaintext) < 20:
            raise WeComCryptoError("decrypted payload is too short")

        content = plaintext[16:]
        msg_len = struct.unpack("!I", content[:4])[0]
        msg = content[4 : 4 + msg_len]
        actual_receive_id = content[4 + msg_len :].decode("utf-8")

        if self.receive_id and actual_receive_id != self.receive_id:
            raise WeComCryptoError("receive_id mismatch")

        return msg.decode("utf-8")

    def encrypt(self, message: str, nonce: str | None = None) -> EncryptedMessage:
        nonce = nonce or secrets.token_hex(8)
        timestamp = int(time.time())
        message_bytes = message.encode("utf-8")
        payload = (
            secrets.token_bytes(16)
            + struct.pack("!I", len(message_bytes))
            + message_bytes
            + self.receive_id.encode("utf-8")
        )
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = base64.b64encode(cipher.encrypt(_pkcs7_pad(payload))).decode("utf-8")
        signature = make_signature(self.token, str(timestamp), nonce, encrypted)
        return EncryptedMessage(
            encrypt=encrypted,
            msgsignature=signature,
            timestamp=timestamp,
            nonce=nonce,
        )
