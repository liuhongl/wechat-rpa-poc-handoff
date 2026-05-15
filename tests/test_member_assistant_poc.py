import unittest

from app.member_assistant_poc import (
    DesktopSendPlan,
    build_at_member_applescript,
    build_send_text_applescript,
    extract_plain_text_records,
)


class MemberAssistantPocTests(unittest.TestCase):
    def test_extract_plain_text_records_filters_target_room(self) -> None:
        messages = [
            {
                "seq": 11,
                "msgid": "msg-1_external",
                "action": "send",
                "from": "wm_customer",
                "roomid": "target-room",
                "msgtime": 1710000000000,
                "msgtype": "text",
                "text": {"content": "@小助理 需要经营证明吗"},
            },
            {
                "seq": 12,
                "msgid": "msg-2_external",
                "action": "send",
                "from": "wm_customer",
                "roomid": "other-room",
                "msgtime": 1710000001000,
                "msgtype": "text",
                "text": {"content": "不应该被读取"},
            },
        ]

        records = extract_plain_text_records(messages, target_roomid="target-room")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].seq, 11)
        self.assertEqual(records[0].roomid, "target-room")
        self.assertEqual(records[0].content, "@小助理 需要经营证明吗")

    def test_build_send_text_applescript_defaults_to_dry_run(self) -> None:
        script = build_send_text_applescript(
            DesktopSendPlan(
                app_name="企业微信",
                chat_name='测试"客户群',
                message="POC测试：只输入不发送",
                send=False,
            )
        )

        self.assertIn('set targetChat to "测试\\"客户群"', script)
        self.assertIn('set shouldSend to false', script)
        self.assertIn("keystroke targetMessage", script)
        self.assertNotIn("key code 36 -- send", script)

    def test_build_at_member_applescript_selects_mention_before_text(self) -> None:
        script = build_at_member_applescript(
            app_name="企业微信",
            chat_name="外部客户群",
            member_name="11",
            message="账单还有3天到期，请确认。",
            send=True,
        )

        self.assertIn('set mentionText to "@11"', script)
        self.assertIn("key code 36 -- select mention candidate", script)
        self.assertIn('set shouldSend to true', script)
        self.assertIn("key code 36 -- send", script)


if __name__ == "__main__":
    unittest.main()
