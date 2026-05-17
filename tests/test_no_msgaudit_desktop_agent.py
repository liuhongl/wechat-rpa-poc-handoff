import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.member_assistant_poc import GroupReplyTarget, MultiGroupReplyJob
from app.no_msgaudit_desktop_agent import (
    WeComDesktopSnapshot,
    WeComEvent,
    build_desktop_snapshot_from_accessibility_tree_text,
    build_desktop_snapshot_from_ui_text,
    build_wecom_events_from_ui_snapshot,
    preflight_report_to_dict,
    reply_job_to_send_plan,
    send_plan_to_dict,
    validate_send_preflight,
    wecom_event_to_plain_text_record,
)


class NoMsgAuditDesktopAgentTests(unittest.TestCase):
    def test_builds_standard_wecom_events_from_gui_snapshot(self) -> None:
        targets = [
            GroupReplyTarget(
                roomid="wr_auto_loan_group",
                chat_name="汽车贷款小助手",
            )
        ]

        events = build_wecom_events_from_ui_snapshot(
            "汽车贷款小助手 [有人@我] sky: 需要经营证明吗 @刘红利",
            group_targets=targets,
            assistant_name="刘红利",
            detected_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="snapshot-1",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利")
        self.assertEqual(events[0].source, "desktop_ui")
        self.assertEqual(events[0].chat_name, "汽车贷款小助手")
        self.assertEqual(events[0].sender_name, "sky")
        self.assertEqual(events[0].content, "需要经营证明吗 @刘红利")
        self.assertEqual(events[0].assistant_name, "刘红利")
        self.assertEqual(events[0].detected_at, "2026-05-17T10:00:00+08:00")
        self.assertEqual(events[0].confidence, 1.0)
        self.assertEqual(events[0].raw_snapshot_ref, "snapshot-1")

    def test_converts_wecom_event_to_existing_plain_text_record(self) -> None:
        event = WeComEvent(
            event_id="ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
            source="desktop_ui",
            chat_name="汽车贷款小助手",
            sender_name="sky",
            content="需要经营证明吗 @刘红利",
            assistant_name="刘红利",
            detected_at="2026-05-17T10:00:00+08:00",
            confidence=1.0,
            raw_snapshot_ref="snapshot-1",
        )

        record = wecom_event_to_plain_text_record(
            event,
            roomid_by_chat_name={"汽车贷款小助手": "wr_auto_loan_group"},
        )

        self.assertEqual(record.msgid, event.event_id)
        self.assertEqual(record.roomid, "wr_auto_loan_group")
        self.assertEqual(record.sender, "sky")
        self.assertEqual(record.content, "需要经营证明吗 @刘红利")

    def test_reply_job_to_send_plan_defaults_to_safe_draft_mode(self) -> None:
        job = MultiGroupReplyJob(
            roomid="wr_auto_loan_group",
            chat_name="汽车贷款小助手",
            source_msgid="ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
            sender="sky",
            content="需要经营证明吗 @刘红利",
            reply_content="回复内容",
            matched_question="需要经营证明吗",
            score=1.0,
            handoff=False,
            question_content="需要经营证明吗",
            applescript="",
        )

        plan = reply_job_to_send_plan(job)
        payload = send_plan_to_dict(plan)

        self.assertEqual(plan.mode, "draft")
        self.assertTrue(plan.requires_operator_confirm)
        self.assertFalse(payload["send"])
        self.assertEqual(payload["chat_name"], "汽车贷款小助手")
        self.assertEqual(payload["reply_content"], "回复内容")

    def test_no_msgaudit_desktop_agent_poc_outputs_events_jobs_and_send_plans(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_agent_poc.py"

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--assistant-name",
                "刘红利",
                "--ignore-state",
            ],
            text=True,
            capture_output=True,
            check=True,
        )

        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
        row_types = {row["type"] for row in rows}

        self.assertIn("wecom_event", row_types)
        self.assertIn("reply_job", row_types)
        self.assertIn("send_plan", row_types)
        self.assertIn('"mode": "draft"', result.stdout)
        self.assertIn('"send": false', result.stdout)

    def test_no_msgaudit_desktop_agent_poc_outputs_preflight_when_snapshot_is_provided(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_agent_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "desktop_snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "current_chat_name": "汽车贷款小助手",
                        "selected_chat_name": "汽车贷款小助手",
                        "input_text": "",
                        "app_online": True,
                        "window_visible": True,
                        "captured_at": "2026-05-17T10:00:00+08:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-snapshot-json",
                    str(snapshot_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
        preflight_rows = [row for row in rows if row["type"] == "send_preflight"]

        self.assertEqual(len(preflight_rows), 2)
        self.assertTrue(preflight_rows[0]["ok"])
        self.assertEqual(preflight_rows[0]["status"], "ready_to_draft")
        self.assertFalse(preflight_rows[0]["can_send"])
        self.assertFalse(preflight_rows[1]["ok"])
        self.assertEqual(preflight_rows[1]["status"], "blocked")
        self.assertIn("current_chat_mismatch", preflight_rows[1]["failures"])

    def test_builds_desktop_snapshot_from_structured_ui_text(self) -> None:
        snapshot = build_desktop_snapshot_from_ui_text(
            """
            当前群名: 汽车贷款小助手
            左侧选中会话: 汽车贷款小助手
            输入框:
            企业微信在线: 是
            窗口可见: 是
            """,
            captured_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="computer-use:state-1",
        )

        self.assertEqual(snapshot.current_chat_name, "汽车贷款小助手")
        self.assertEqual(snapshot.selected_chat_name, "汽车贷款小助手")
        self.assertEqual(snapshot.input_text, "")
        self.assertTrue(snapshot.app_online)
        self.assertTrue(snapshot.window_visible)
        self.assertEqual(snapshot.captured_at, "2026-05-17T10:00:00+08:00")
        self.assertEqual(snapshot.raw_snapshot_ref, "computer-use:state-1")

    def test_builds_desktop_snapshot_from_english_ui_text_and_parses_false_booleans(self) -> None:
        snapshot = build_desktop_snapshot_from_ui_text(
            """
            current_chat_name: 客户联系
            selected_chat_name: 汽车金融VIP群
            input_text: 未发送草稿
            app_online: false
            window_visible: false
            """,
            captured_at="2026-05-17T10:00:00+08:00",
        )

        self.assertEqual(snapshot.current_chat_name, "客户联系")
        self.assertEqual(snapshot.selected_chat_name, "汽车金融VIP群")
        self.assertEqual(snapshot.input_text, "未发送草稿")
        self.assertFalse(snapshot.app_online)
        self.assertFalse(snapshot.window_visible)

    def test_builds_desktop_snapshot_from_computer_use_accessibility_tree_text(self) -> None:
        targets = [
            GroupReplyTarget(roomid="wr_auto_loan_group", chat_name="汽车贷款小助手"),
            GroupReplyTarget(roomid="wr_vip_group", chat_name="汽车金融VIP群"),
        ]
        snapshot = build_desktop_snapshot_from_accessibility_tree_text(
            """
            22 row (selected)
              23 单元格 (selected)
                24 图像
                25 text 汽车金融VIP群 邀请微信的小飞侠加入外部群聊失败
                26 文本 1分钟前
                27 文本输入区 外部
            81 分离器 (disabled, settable, float) 250
            83 文本栏 (settable, string) 汽车金融VIP群
            84 文本 由企业微信用户创建的外部群，含1位外部联系人 | 群主: 刘红利
            111 滚动区
              112 文本输入区 (settable, string)
            The focused UI element is 112 文本输入区 (settable, string).
            """,
            group_targets=targets,
            captured_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="computer-use:企业微信",
        )

        self.assertEqual(snapshot.current_chat_name, "汽车金融VIP群")
        self.assertEqual(snapshot.selected_chat_name, "汽车金融VIP群")
        self.assertEqual(snapshot.input_text, "")
        self.assertTrue(snapshot.app_online)
        self.assertTrue(snapshot.window_visible)
        self.assertEqual(snapshot.raw_snapshot_ref, "computer-use:企业微信")

    def test_no_msgaudit_desktop_agent_poc_can_build_preflight_from_snapshot_text_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_agent_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "desktop_snapshot.txt"
            snapshot_path.write_text(
                "\n".join(
                    [
                        "当前群名: 汽车贷款小助手",
                        "左侧选中会话: 汽车贷款小助手",
                        "输入框:",
                        "企业微信在线: 是",
                        "窗口可见: 是",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-snapshot-text-file",
                    str(snapshot_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn('"type": "send_preflight"', result.stdout)
        self.assertIn('"status": "ready_to_draft"', result.stdout)
        self.assertIn('"status": "blocked"', result.stdout)

    def test_no_msgaudit_desktop_agent_poc_can_build_preflight_from_accessibility_tree_text_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_agent_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "accessibility_tree.txt"
            snapshot_path.write_text(
                "\n".join(
                    [
                        "22 row (selected)",
                        "  25 text 汽车金融VIP群 邀请微信的小飞侠加入外部群聊失败",
                        "83 文本栏 (settable, string) 汽车金融VIP群",
                        "112 文本输入区 (settable, string)",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-text-file",
                    str(snapshot_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn('"type": "send_preflight"', result.stdout)
        self.assertIn('"expected_chat_name": "汽车金融VIP群"', result.stdout)
        self.assertIn('"status": "ready_to_draft"', result.stdout)

    def test_no_msgaudit_desktop_scan_poc_outputs_heartbeat_snapshot_and_preflight_rows(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            loan_tree = tmp_path / "loan_tree.txt"
            vip_tree = tmp_path / "vip_tree.txt"
            out_path = tmp_path / "scan.jsonl"
            loan_tree.write_text(
                "\n".join(
                    [
                        "22 row (selected)",
                        "  25 text 汽车贷款小助手 是否需要经营证明取决于具体产品和客户身份。",
                        "83 文本栏 (settable, string) 汽车贷款小助手",
                        "112 文本输入区 (settable, string)",
                    ]
                ),
                encoding="utf-8",
            )
            vip_tree.write_text(
                "\n".join(
                    [
                        "22 row (selected)",
                        "  25 text 汽车金融VIP群 邀请微信的小飞侠加入外部群聊失败",
                        "83 文本栏 (settable, string) 汽车金融VIP群",
                        "112 文本输入区 (settable, string)",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-text-file",
                    str(loan_tree),
                    "--desktop-accessibility-tree-text-file",
                    str(vip_tree),
                    "--iterations",
                    "2",
                    "--interval-seconds",
                    "0",
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]

        row_types = [row["type"] for row in rows]
        heartbeat_rows = [row for row in rows if row["type"] == "scan_heartbeat"]
        snapshot_rows = [row for row in rows if row["type"] == "desktop_snapshot"]
        preflight_rows = [row for row in rows if row["type"] == "send_preflight"]

        self.assertIn('"type": "scan_heartbeat"', result.stdout)
        self.assertEqual(row_types.count("scan_heartbeat"), 2)
        self.assertEqual(len(heartbeat_rows), 2)
        self.assertEqual(len(snapshot_rows), 2)
        self.assertEqual(len(preflight_rows), 4)
        self.assertEqual(snapshot_rows[0]["current_chat_name"], "汽车贷款小助手")
        self.assertEqual(snapshot_rows[1]["current_chat_name"], "汽车金融VIP群")
        self.assertTrue(any(row["status"] == "ready_to_draft" for row in preflight_rows))
        self.assertTrue(any(row["status"] == "blocked" for row in preflight_rows))

    def test_send_preflight_allows_safe_draft_when_desktop_snapshot_matches(self) -> None:
        plan = self._send_plan(mode="draft")
        snapshot = WeComDesktopSnapshot(
            current_chat_name="汽车贷款小助手",
            selected_chat_name="汽车贷款小助手",
            input_text="",
            app_online=True,
            window_visible=True,
            captured_at="2026-05-17T10:00:00+08:00",
        )

        report = validate_send_preflight(plan, snapshot, processed_event_ids=set())
        payload = preflight_report_to_dict(report)

        self.assertTrue(report.ok)
        self.assertEqual(report.status, "ready_to_draft")
        self.assertFalse(report.can_send)
        self.assertEqual(report.failures, [])
        self.assertEqual(payload["verified_chat_name"], "汽车贷款小助手")

    def test_send_preflight_blocks_wrong_chat_and_nonempty_input(self) -> None:
        plan = self._send_plan(mode="draft")
        snapshot = WeComDesktopSnapshot(
            current_chat_name="客户联系",
            selected_chat_name="汽车金融VIP群",
            input_text="未发送的旧草稿",
            app_online=True,
            window_visible=True,
            captured_at="2026-05-17T10:00:00+08:00",
        )

        report = validate_send_preflight(plan, snapshot, processed_event_ids=set())

        self.assertFalse(report.ok)
        self.assertFalse(report.can_send)
        self.assertIn("current_chat_mismatch", report.failures)
        self.assertIn("selected_chat_mismatch", report.failures)
        self.assertIn("input_not_empty", report.failures)

    def test_send_preflight_blocks_processed_event_and_offline_desktop(self) -> None:
        plan = self._send_plan(mode="auto_send")
        snapshot = WeComDesktopSnapshot(
            current_chat_name="汽车贷款小助手",
            selected_chat_name="汽车贷款小助手",
            input_text="",
            app_online=False,
            window_visible=False,
            captured_at="2026-05-17T10:00:00+08:00",
        )

        report = validate_send_preflight(
            plan,
            snapshot,
            processed_event_ids={plan.event_id},
        )

        self.assertFalse(report.ok)
        self.assertFalse(report.can_send)
        self.assertIn("app_offline", report.failures)
        self.assertIn("window_not_visible", report.failures)
        self.assertIn("already_processed", report.failures)

    def test_send_preflight_allows_auto_send_only_when_all_checks_pass(self) -> None:
        plan = self._send_plan(mode="auto_send")
        snapshot = WeComDesktopSnapshot(
            current_chat_name="汽车贷款小助手",
            selected_chat_name="汽车贷款小助手",
            input_text="",
            app_online=True,
            window_visible=True,
            captured_at="2026-05-17T10:00:00+08:00",
        )

        report = validate_send_preflight(plan, snapshot, processed_event_ids=set())

        self.assertTrue(report.ok)
        self.assertEqual(report.status, "ready_to_send")
        self.assertTrue(report.can_send)

    def _send_plan(self, *, mode: str):
        job = MultiGroupReplyJob(
            roomid="wr_auto_loan_group",
            chat_name="汽车贷款小助手",
            source_msgid="ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
            sender="sky",
            content="需要经营证明吗 @刘红利",
            reply_content="回复内容",
            matched_question="需要经营证明吗",
            score=1.0,
            handoff=False,
            question_content="需要经营证明吗",
            applescript="",
        )
        return reply_job_to_send_plan(job, mode=mode)


if __name__ == "__main__":
    unittest.main()
