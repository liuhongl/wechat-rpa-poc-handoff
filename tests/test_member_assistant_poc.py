import unittest
from datetime import date

from app.member_assistant_poc import (
    BillReminder,
    DesktopSendPlan,
    PlainTextRecord,
    build_desktop_preflight_report,
    build_at_member_applescript,
    build_send_text_applescript,
    extract_wecom_ui_mention_records,
    extract_plain_text_records,
    filter_unprocessed_records,
    plan_bill_reminder_actions,
    plan_reply_actions,
    record_key,
    resolve_assistant_names,
    resolve_desktop_chat_name,
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

    def test_extract_wecom_ui_mention_records_from_conversation_list(self) -> None:
        ui_text = """
25 text 汽车贷款小助手 [有人@我] sky: 需要经营证明吗\u2005@刘红利
26 文本 1分钟前
32 text 测试 kෆy: 1
"""

        records = extract_wecom_ui_mention_records(
            ui_text,
            target_chat_name="汽车贷款小助手",
            roomid="汽车贷款小助手",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].sender, "sky")
        self.assertEqual(records[0].content, "需要经营证明吗\u2005@刘红利")
        self.assertEqual(records[0].msgid, "ui:汽车贷款小助手:sky:需要经营证明吗\u2005@刘红利")

    def test_extract_wecom_ui_mention_records_ignores_other_chats(self) -> None:
        ui_text = """
25 text 其他群 [有人@我] sky: 需要经营证明吗\u2005@刘红利
"""

        records = extract_wecom_ui_mention_records(
            ui_text,
            target_chat_name="汽车贷款小助手",
            roomid="汽车贷款小助手",
        )

        self.assertEqual(records, [])

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

    def test_plan_reply_actions_supports_member_name_as_assistant_name(self) -> None:
        records = [
            PlainTextRecord(
                seq=24,
                msgid="live-sky-mention",
                action="send",
                sender="sky",
                roomid="target-room",
                msgtime=1710000000000,
                content="需要经营证明吗\u2005@刘红利",
            )
        ]

        default_actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
        )
        member_name_actions = plan_reply_actions(
            records,
            assistant_names=["刘红利"],
            chat_name="外部客户群",
        )

        self.assertEqual(default_actions, [])
        self.assertEqual(len(member_name_actions), 1)
        self.assertEqual(member_name_actions[0].question_content, "需要经营证明吗")
        self.assertIn("经营证明", member_name_actions[0].reply_content)

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

    def test_plan_reply_actions_ignores_assistant_sender_to_prevent_loop(self) -> None:
        records = [
            PlainTextRecord(
                seq=33,
                msgid="assistant-self-message",
                action="send",
                sender="wm_assistant_member",
                roomid="target-room",
                msgtime=1710000000000,
                content="@小助理 需要经营证明吗",
            ),
            PlainTextRecord(
                seq=34,
                msgid="customer-message",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000001000,
                content="@小助理 需要经营证明吗",
            ),
        ]

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
            assistant_sender_ids=["wm_assistant_member"],
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].record.msgid, "customer-message")

    def test_plan_reply_actions_uses_previous_question_when_next_message_only_mentions(self) -> None:
        records = [
            PlainTextRecord(
                seq=35,
                msgid="customer-question",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000000000,
                content="需要经营证明吗",
            ),
            PlainTextRecord(
                seq=36,
                msgid="customer-mention",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000005000,
                content="@小助理",
            ),
        ]

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].record.msgid, "customer-mention")
        self.assertEqual(actions[0].question_content, "需要经营证明吗")
        self.assertIn("经营证明", actions[0].reply_content)

    def test_plan_reply_actions_merges_recent_customer_messages_before_mention(self) -> None:
        records = [
            PlainTextRecord(
                seq=37,
                msgid="customer-context-1",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000000000,
                content="我想办经营类贷款",
            ),
            PlainTextRecord(
                seq=38,
                msgid="customer-context-2",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000003000,
                content="需要经营证明吗",
            ),
            PlainTextRecord(
                seq=39,
                msgid="customer-mention",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000006000,
                content="@小助理",
            ),
        ]

        actions = plan_reply_actions(
            records,
            assistant_names=["小助理"],
            chat_name="外部客户群",
        )

        self.assertEqual(len(actions), 1)
        self.assertIn("我想办经营类贷款", actions[0].question_content or "")
        self.assertIn("需要经营证明吗", actions[0].question_content or "")
        self.assertFalse(actions[0].handoff)

    def test_filter_unprocessed_records_uses_msgid_or_seq_fallback(self) -> None:
        records = [
            PlainTextRecord(
                seq=41,
                msgid="msg-41",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000000000,
                content="@小助理 需要经营证明吗",
            ),
            PlainTextRecord(
                seq=42,
                msgid="",
                action="send",
                sender="wm_customer",
                roomid="target-room",
                msgtime=1710000001000,
                content="@小助理 贷款利率是多少",
            ),
        ]

        processed = {record_key(records[0]), "target-room:42"}

        self.assertEqual(filter_unprocessed_records(records, processed), [])

    def test_build_desktop_preflight_report_marks_missing_chat_name(self) -> None:
        report = build_desktop_preflight_report(
            app_name="企业微信",
            chat_name="",
            platform="darwin",
            send=False,
            run=False,
        )

        self.assertFalse(report.ok)
        self.assertIn("chat_name", report.missing)
        self.assertFalse(report.will_run)
        self.assertFalse(report.will_send)

    def test_build_desktop_preflight_report_accepts_darwin_config(self) -> None:
        report = build_desktop_preflight_report(
            app_name="企业微信",
            chat_name="外部客户群",
            platform="darwin",
            send=True,
            run=False,
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.app_name, "企业微信")
        self.assertEqual(report.chat_name, "外部客户群")
        self.assertTrue(report.will_run)
        self.assertTrue(report.will_send)

    def test_resolve_desktop_chat_name_requires_real_name_when_running(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing --chat-name"):
            resolve_desktop_chat_name("", run=True)

    def test_resolve_desktop_chat_name_keeps_simulation_fallback_for_plan_only(self) -> None:
        self.assertEqual(
            resolve_desktop_chat_name("", run=False),
            "模拟外部客户群",
        )

    def test_resolve_assistant_names_prefers_explicit_then_env_then_fallback(self) -> None:
        self.assertEqual(resolve_assistant_names(["刘红利"], env_value="小助理"), ["刘红利"])
        self.assertEqual(resolve_assistant_names([], env_value="刘红利,小助理"), ["刘红利", "小助理"])
        self.assertEqual(resolve_assistant_names([], env_value=""), ["小助理"])

    def test_plan_bill_reminder_actions_reminds_three_days_before_once(self) -> None:
        reminders = [
            BillReminder(
                bill_id="bill-sky-001",
                roomid="target-room",
                chat_name="外部客户群",
                member_name="sky",
                due_date=date(2026, 5, 18),
            )
        ]

        actions = plan_bill_reminder_actions(
            reminders,
            today=date(2026, 5, 15),
            sent_keys=[],
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].days_before, 3)
        self.assertIn("3天", actions[0].message)
        self.assertIn('set mentionText to "@sky"', actions[0].applescript)

        duplicate_actions = plan_bill_reminder_actions(
            reminders,
            today=date(2026, 5, 15),
            sent_keys=[actions[0].state_key],
        )
        self.assertEqual(duplicate_actions, [])

    def test_plan_bill_reminder_actions_skips_settled_and_outside_window(self) -> None:
        reminders = [
            BillReminder(
                bill_id="settled-bill",
                roomid="target-room",
                chat_name="外部客户群",
                member_name="sky",
                due_date=date(2026, 5, 18),
                status="settled",
            ),
            BillReminder(
                bill_id="future-bill",
                roomid="target-room",
                chat_name="外部客户群",
                member_name="sky",
                due_date=date(2026, 5, 25),
            ),
        ]

        actions = plan_bill_reminder_actions(
            reminders,
            today=date(2026, 5, 15),
            sent_keys=[],
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
