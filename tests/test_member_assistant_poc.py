import unittest

from app.member_assistant_poc import (
    DesktopSendPlan,
    build_at_member_applescript,
    build_send_text_applescript,
    extract_plain_text_records,
    plan_reply_actions,
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

    def test_plan_reply_actions_only_replies_to_assistant_mentions(self) -> None:
        records = extract_plain_text_records(
            [
                {
                    "seq": 21,
                    "msgid": "msg-21_external",
                    "action": "send",
                    "from": "wm_customer",
                    "roomid": "target-room",
                    "msgtime": 1710000000000,
                    "msgtype": "text",
                    "text": {"content": "@小助理 贷款利率是多少"},
                },
                {
                    "seq": 22,
                    "msgid": "msg-22_external",
                    "action": "send",
                    "from": "wm_customer",
                    "roomid": "target-room",
                    "msgtime": 1710000001000,
                    "msgtype": "text",
                    "text": {"content": "账单什么时候到期？"},
                },
            ],
            target_roomid="target-room",
        )

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
            app_name="企业微信",
            require_mention=True,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].record.msgid, "msg-21_external")
        self.assertIn("利率", actions[0].reply_content)
        self.assertIn("set targetChat to \"外部客户群\"", actions[0].applescript)
        self.assertNotIn("key code 36 -- send", actions[0].applescript)

    def test_plan_reply_actions_answers_business_certificate_question(self) -> None:
        records = extract_plain_text_records(
            [
                {
                    "seq": 23,
                    "msgid": "msg-23_external",
                    "action": "send",
                    "from": "wm_customer",
                    "roomid": "target-room",
                    "msgtime": 1710000000000,
                    "msgtype": "text",
                    "text": {"content": "@小助理 需要经营证明吗"},
                }
            ],
            target_roomid="target-room",
        )

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
            app_name="企业微信",
            require_mention=True,
        )

        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].handoff)
        self.assertIn("经营证明", actions[0].reply_content)

    def test_plan_reply_actions_can_include_non_mentions_when_allowed(self) -> None:
        records = extract_plain_text_records(
            [
                {
                    "seq": 31,
                    "msgid": "msg-31_external",
                    "action": "send",
                    "from": "wm_customer",
                    "roomid": "target-room",
                    "msgtime": 1710000000000,
                    "msgtype": "text",
                    "text": {"content": "还款日是哪天"},
                }
            ],
            target_roomid="target-room",
        )

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
            app_name="企业微信",
            require_mention=False,
        )

        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].handoff)
        self.assertIn("还款日", actions[0].reply_content)


if __name__ == "__main__":
    unittest.main()
