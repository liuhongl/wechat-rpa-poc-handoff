from __future__ import annotations

import unittest

from app.wecom_ws import build_ping, build_send_msg, build_subscribe, is_ok_response


class WeComWsMessageTests(unittest.TestCase):
    def test_build_subscribe_message(self) -> None:
        payload = build_subscribe(
            bot_id="bot-123",
            secret="secret-456",
            req_id="req-subscribe",
        )

        self.assertEqual(payload["cmd"], "aibot_subscribe")
        self.assertEqual(payload["headers"], {"req_id": "req-subscribe"})
        self.assertEqual(
            payload["body"],
            {"bot_id": "bot-123", "secret": "secret-456"},
        )

    def test_build_group_markdown_send_message(self) -> None:
        payload = build_send_msg(
            chatid="chat-123",
            content="账单还有3天到期，请及时跟进。",
            req_id="req-send",
            chat_type=2,
        )

        self.assertEqual(payload["cmd"], "aibot_send_msg")
        self.assertEqual(payload["headers"], {"req_id": "req-send"})
        self.assertEqual(payload["body"]["chatid"], "chat-123")
        self.assertEqual(payload["body"]["chat_type"], 2)
        self.assertEqual(payload["body"]["msgtype"], "markdown")
        self.assertEqual(
            payload["body"]["markdown"],
            {"content": "账单还有3天到期，请及时跟进。"},
        )

    def test_build_ping_message(self) -> None:
        payload = build_ping(req_id="req-ping")

        self.assertEqual(payload["cmd"], "ping")
        self.assertEqual(payload["headers"], {"req_id": "req-ping"})

    def test_is_ok_response_matches_req_id_and_errcode(self) -> None:
        payload = {
            "headers": {"req_id": "req-subscribe"},
            "errcode": 0,
            "errmsg": "ok",
        }

        self.assertTrue(is_ok_response(payload, "req-subscribe"))
        self.assertFalse(is_ok_response(payload, "other-req"))
        self.assertFalse(is_ok_response({**payload, "errcode": 1}, "req-subscribe"))


if __name__ == "__main__":
    unittest.main()
