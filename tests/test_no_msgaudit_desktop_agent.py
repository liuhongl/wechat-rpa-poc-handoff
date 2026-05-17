import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.member_assistant_poc import GroupReplyTarget, MultiGroupReplyJob
from app.no_msgaudit_desktop_agent import (
    WeComDesktopSnapshot,
    WeComEvent,
    build_desktop_snapshot_from_accessibility_tree_text,
    build_desktop_snapshot_from_ui_text,
    build_wecom_events_from_accessibility_tree_text,
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

    def test_builds_desktop_snapshot_from_swift_ax_accessibility_tree_text(self) -> None:
        targets = [
            GroupReplyTarget(roomid="wr_auto_loan_group", chat_name="汽车贷款小助手"),
            GroupReplyTarget(roomid="wr_vip_group", chat_name="汽车金融VIP群"),
        ]
        snapshot = build_desktop_snapshot_from_accessibility_tree_text(
            """
            AXApplication 企业微信
              AXWindow 企业微信
                AXSplitGroup
                  AXScrollArea
                    AXTable
                      AXRow (selected)
                        AXCell (selected)
                          AXImage
                          AXStaticText 汽车金融VIP群
                          AXStaticText 邀请的小飞侠加入外部群聊失败
                          AXTextArea 外部
                  AXTextField 汽车金融VIP群
                  AXStaticText 由企业微信用户创建的外部群，含1位外部联系人 | 群主: 刘红利
                  AXTextArea
            """,
            group_targets=targets,
            captured_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="swift-ax:企业微信",
        )

        self.assertEqual(snapshot.current_chat_name, "汽车金融VIP群")
        self.assertEqual(snapshot.selected_chat_name, "汽车金融VIP群")
        self.assertEqual(snapshot.input_text, "")
        self.assertTrue(snapshot.app_online)
        self.assertTrue(snapshot.window_visible)
        self.assertEqual(snapshot.raw_snapshot_ref, "swift-ax:企业微信")

    def test_builds_wecom_events_from_swift_ax_current_chat_message_rows(self) -> None:
        targets = [
            GroupReplyTarget(roomid="wr_vip_group", chat_name="汽车金融VIP群"),
        ]

        events = build_wecom_events_from_accessibility_tree_text(
            """
            AXApplication 企业微信
              AXWindow 企业微信
                AXTextField 汽车金融VIP群
                AXStaticText 由企业微信用户创建的外部群，含1位外部联系人 | 群主: 刘红利
                AXScrollArea
                  AXTable
                    AXRow
                      AXCell
                        AXStaticText 16:48
                        AXStaticText sky
                        AXTextArea 需要经营证明吗 @刘红利
                    AXRow
                      AXCell
                        AXStaticText 刘红利
                        AXTextArea 是否需要经营证明取决于具体产品和客户身份。
            """,
            group_targets=targets,
            assistant_name="刘红利",
            detected_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="swift-ax:企业微信",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "ax:汽车金融VIP群:sky:需要经营证明吗 @刘红利#1")
        self.assertEqual(events[0].source, "desktop_accessibility_tree")
        self.assertEqual(events[0].chat_name, "汽车金融VIP群")
        self.assertEqual(events[0].sender_name, "sky")
        self.assertEqual(events[0].content, "需要经营证明吗 @刘红利")
        self.assertEqual(events[0].assistant_name, "刘红利")
        self.assertEqual(events[0].detected_at, "2026-05-17T10:00:00+08:00")
        self.assertEqual(events[0].confidence, 0.85)
        self.assertEqual(events[0].raw_snapshot_ref, "swift-ax:企业微信")

    def test_builds_distinct_ax_events_for_repeated_identical_visible_mentions(self) -> None:
        targets = [
            GroupReplyTarget(roomid="wr_vip_group", chat_name="汽车金融VIP群"),
        ]

        events = build_wecom_events_from_accessibility_tree_text(
            """
            AXApplication 企业微信
              AXWindow 企业微信
                AXTextField 汽车金融VIP群
                AXScrollArea
                  AXTable
                    AXRow
                      AXCell
                        AXStaticText 16:48
                        AXStaticText sky
                        AXTextArea 需要经营证明吗 @刘红利
                    AXRow
                      AXCell
                        AXStaticText 16:49
                        AXStaticText sky
                        AXTextArea 需要经营证明吗 @刘红利
            """,
            group_targets=targets,
            assistant_name="刘红利",
            detected_at="2026-05-17T10:00:00+08:00",
            raw_snapshot_ref="swift-ax:企业微信",
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].sender_name, "sky")
        self.assertEqual(events[1].sender_name, "sky")
        self.assertEqual(events[0].content, "需要经营证明吗 @刘红利")
        self.assertEqual(events[1].content, "需要经营证明吗 @刘红利")
        self.assertNotEqual(events[0].event_id, events[1].event_id)
        self.assertTrue(events[0].event_id.endswith("#1"))
        self.assertTrue(events[1].event_id.endswith("#2"))

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

    def test_no_msgaudit_desktop_agent_poc_can_build_events_from_accessibility_tree_text_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_agent_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "accessibility_tree.txt"
            out_path = Path(tmpdir) / "plan.jsonl"
            snapshot_path.write_text(
                "\n".join(
                    [
                        "AXApplication 企业微信",
                        "  AXWindow 企业微信",
                        "    AXRow (selected)",
                        "      AXCell (selected)",
                        "        AXStaticText 汽车贷款小助手",
                        "    AXTextField 汽车贷款小助手",
                        "    AXScrollArea",
                        "      AXTable",
                        "        AXRow",
                        "          AXCell",
                        "            AXStaticText 16:48",
                        "            AXStaticText sky",
                        "            AXTextArea 需要经营证明吗 @刘红利",
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
                    "--events-accessibility-tree-text-file",
                    str(snapshot_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]

        self.assertIn('"source": "desktop_accessibility_tree"', result.stdout)
        self.assertTrue(any(row["type"] == "wecom_event" for row in rows))
        self.assertTrue(any(row["type"] == "reply_job" for row in rows))
        self.assertTrue(any(row["type"] == "send_plan" for row in rows))

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

    def test_no_msgaudit_desktop_scan_poc_can_poll_accessibility_tree_directory(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            (snapshot_dir / "001-loan.txt").write_text(
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
            (snapshot_dir / "002-vip.txt").write_text(
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

            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
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

        snapshot_rows = [row for row in rows if row["type"] == "desktop_snapshot"]

        self.assertEqual(len(snapshot_rows), 2)
        self.assertTrue(snapshot_rows[0]["raw_snapshot_ref"].endswith("001-loan.txt"))
        self.assertTrue(snapshot_rows[1]["raw_snapshot_ref"].endswith("002-vip.txt"))
        self.assertEqual(snapshot_rows[0]["current_chat_name"], "汽车贷款小助手")
        self.assertEqual(snapshot_rows[1]["current_chat_name"], "汽车金融VIP群")

    def test_no_msgaudit_desktop_scan_poc_can_build_events_from_accessibility_tree_directory(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            (snapshot_dir / "001-loan.txt").write_text(
                "\n".join(
                    [
                        "AXApplication 企业微信",
                        "  AXWindow 企业微信",
                        "    AXRow (selected)",
                        "      AXCell (selected)",
                        "        AXStaticText 汽车贷款小助手",
                        "    AXTextField 汽车贷款小助手",
                        "    AXScrollArea",
                        "      AXTable",
                        "        AXRow",
                        "          AXCell",
                        "            AXStaticText 16:48",
                        "            AXStaticText sky",
                        "            AXTextArea 需要经营证明吗 @刘红利",
                        "    AXTextArea",
                    ]
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--events-from-accessibility-tree",
                    "--iterations",
                    "1",
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

        event_rows = [row for row in rows if row["type"] == "wecom_event"]
        job_rows = [row for row in rows if row["type"] == "reply_job"]
        plan_rows = [row for row in rows if row["type"] == "send_plan"]
        preflight_rows = [row for row in rows if row["type"] == "send_preflight"]

        self.assertEqual(len(event_rows), 1)
        self.assertEqual(event_rows[0]["source"], "desktop_accessibility_tree")
        self.assertEqual(event_rows[0]["chat_name"], "汽车贷款小助手")
        self.assertEqual(event_rows[0]["sender_name"], "sky")
        self.assertEqual(len(job_rows), 1)
        self.assertEqual(len(plan_rows), 1)
        self.assertEqual(preflight_rows[0]["status"], "ready_to_draft")

    def test_no_msgaudit_desktop_scan_poc_dedupes_repeated_accessibility_tree_events_in_one_run(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            (snapshot_dir / "001-loan.txt").write_text(
                "\n".join(
                    [
                        "AXApplication 企业微信",
                        "  AXWindow 企业微信",
                        "    AXRow (selected)",
                        "      AXCell (selected)",
                        "        AXStaticText 汽车贷款小助手",
                        "    AXTextField 汽车贷款小助手",
                        "    AXScrollArea",
                        "      AXTable",
                        "        AXRow",
                        "          AXCell",
                        "            AXStaticText 16:48",
                        "            AXStaticText sky",
                        "            AXTextArea 需要经营证明吗 @刘红利",
                        "    AXTextArea",
                    ]
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--events-from-accessibility-tree",
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

        event_rows = [row for row in rows if row["type"] == "wecom_event"]
        job_rows = [row for row in rows if row["type"] == "reply_job"]
        plan_rows = [row for row in rows if row["type"] == "send_plan"]
        heartbeat_rows = [row for row in rows if row["type"] == "scan_heartbeat"]
        preflight_rows = [row for row in rows if row["type"] == "send_preflight"]

        self.assertEqual(len(event_rows), 1)
        self.assertEqual(len(job_rows), 1)
        self.assertEqual(len(plan_rows), 1)
        self.assertEqual(len(preflight_rows), 1)
        self.assertEqual([row["send_plan_count"] for row in heartbeat_rows], [1, 0])

    def test_no_msgaudit_desktop_scan_poc_follow_dir_consumes_each_snapshot_once(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            (snapshot_dir / "001-loan.txt").write_text(
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
            (snapshot_dir / "002-vip.txt").write_text(
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

            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--follow-snapshot-dir",
                    "--events-from-accessibility-tree",
                    "--iterations",
                    "3",
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

        heartbeat_rows = [row for row in rows if row["type"] == "scan_heartbeat"]
        snapshot_rows = [row for row in rows if row["type"] == "desktop_snapshot"]

        self.assertEqual(len(heartbeat_rows), 3)
        self.assertEqual(len(snapshot_rows), 2)
        self.assertTrue(snapshot_rows[0]["raw_snapshot_ref"].endswith("001-loan.txt"))
        self.assertTrue(snapshot_rows[1]["raw_snapshot_ref"].endswith("002-vip.txt"))
        self.assertEqual(heartbeat_rows[2]["status"], "idle")
        self.assertEqual(heartbeat_rows[2]["reason"], "no_new_snapshot")
        self.assertEqual(heartbeat_rows[2]["send_plan_count"], 0)

    def test_no_msgaudit_desktop_scan_poc_follow_dir_requires_accessibility_tree_events(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            snapshot_dir.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--follow-snapshot-dir",
                    "--iterations",
                    "1",
                    "--interval-seconds",
                    "0",
                ],
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--follow-snapshot-dir requires --events-from-accessibility-tree", result.stderr)

    def test_no_msgaudit_desktop_scan_poc_follow_dir_waits_for_late_snapshot(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--follow-snapshot-dir",
                    "--events-from-accessibility-tree",
                    "--iterations",
                    "3",
                    "--interval-seconds",
                    "0.15",
                    "--out",
                    str(out_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.05)
            (snapshot_dir / "001-loan.txt").write_text(
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
            stdout, stderr = process.communicate(timeout=5)

            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('"status": "idle"', stdout)
            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]

        heartbeat_rows = [row for row in rows if row["type"] == "scan_heartbeat"]
        snapshot_rows = [row for row in rows if row["type"] == "desktop_snapshot"]

        self.assertEqual(heartbeat_rows[0]["status"], "idle")
        self.assertEqual(len(snapshot_rows), 1)
        self.assertTrue(snapshot_rows[0]["raw_snapshot_ref"].endswith("001-loan.txt"))

    def test_no_msgaudit_desktop_scan_poc_follow_dir_persists_snapshot_cursor_across_runs(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            cursor_path = tmp_path / "snapshot_cursor.json"
            first_out_path = tmp_path / "first.jsonl"
            second_out_path = tmp_path / "second.jsonl"
            (snapshot_dir / "001-loan.txt").write_text(
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

            base_command = [
                sys.executable,
                str(script),
                "--assistant-name",
                "刘红利",
                "--ignore-state",
                "--desktop-accessibility-tree-dir",
                str(snapshot_dir),
                "--follow-snapshot-dir",
                "--events-from-accessibility-tree",
                "--snapshot-cursor-file",
                str(cursor_path),
                "--iterations",
                "1",
                "--interval-seconds",
                "0",
            ]
            subprocess.run(
                [*base_command, "--out", str(first_out_path)],
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [*base_command, "--out", str(second_out_path)],
                text=True,
                capture_output=True,
                check=True,
            )

            first_rows = [json.loads(line) for line in first_out_path.read_text(encoding="utf-8").splitlines()]
            second_rows = [json.loads(line) for line in second_out_path.read_text(encoding="utf-8").splitlines()]
            cursor_payload = json.loads(cursor_path.read_text(encoding="utf-8"))

        self.assertEqual(len([row for row in first_rows if row["type"] == "desktop_snapshot"]), 1)
        self.assertEqual(len([row for row in second_rows if row["type"] == "desktop_snapshot"]), 0)
        self.assertEqual(second_rows[0]["status"], "idle")
        self.assertEqual(second_rows[0]["reason"], "no_new_snapshot")
        self.assertEqual(len(cursor_payload["consumed_snapshot_paths"]), 1)
        self.assertTrue(cursor_payload["consumed_snapshot_paths"][0].endswith("001-loan.txt"))

    def test_no_msgaudit_desktop_scan_poc_streams_rows_to_out_before_exit(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_scan_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot_dir = tmp_path / "snapshots"
            snapshot_dir.mkdir()
            out_path = tmp_path / "scan.jsonl"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(script),
                    "--assistant-name",
                    "刘红利",
                    "--ignore-state",
                    "--desktop-accessibility-tree-dir",
                    str(snapshot_dir),
                    "--follow-snapshot-dir",
                    "--events-from-accessibility-tree",
                    "--iterations",
                    "5",
                    "--interval-seconds",
                    "0.3",
                    "--out",
                    str(out_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                time.sleep(0.1)
                self.assertIsNone(process.poll(), "scan process exited before proving streaming output")
                self.assertTrue(out_path.exists(), "scan output file should exist while process is still running")
                early_text = out_path.read_text(encoding="utf-8")
                self.assertIn('"type": "scan_heartbeat"', early_text)
                self.assertIn('"status": "idle"', early_text)
            finally:
                stdout, stderr = process.communicate(timeout=5)

            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('"status": "idle"', stdout)

    def test_no_msgaudit_write_snapshot_poc_writes_stdin_to_timestamped_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_write_snapshot_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--snapshot-dir",
                    str(snapshot_dir),
                    "--prefix",
                    "wecom",
                    "--captured-at",
                    "2026-05-17T10:00:00+08:00",
                ],
                input="83 文本栏 (settable, string) 汽车贷款小助手\n",
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            written_path = Path(payload["path"])

            self.assertTrue(written_path.exists())
            self.assertEqual(written_path.parent, snapshot_dir)
            self.assertEqual(written_path.read_text(encoding="utf-8"), "83 文本栏 (settable, string) 汽车贷款小助手\n")
            self.assertTrue(written_path.name.startswith("wecom-20260517T100000"))

    def test_no_msgaudit_scan_health_poc_summarizes_recent_scan_log(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_scan_health_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "desktop_scan_log.jsonl"
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "wecom_event",
                                "event_id": "ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_plan",
                                "job_id": "reply:ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_preflight",
                                "status": "ready_to_draft",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "scan_heartbeat",
                                "iteration": 1,
                                "captured_at": "2026-05-18T10:00:00+08:00",
                                "snapshot_ref": "/tmp/wecom/001.txt",
                                "send_plan_count": 1,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--log-jsonl",
                    str(log_path),
                    "--now",
                    "2026-05-18T10:00:05+08:00",
                    "--max-heartbeat-age-seconds",
                    "10",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        summary = json.loads(result.stdout)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["total_rows"], 4)
        self.assertEqual(summary["heartbeat_count"], 1)
        self.assertEqual(summary["last_heartbeat_age_seconds"], 5)
        self.assertEqual(summary["latest_snapshot_ref"], "/tmp/wecom/001.txt")
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["send_plan_count"], 1)
        self.assertEqual(summary["preflight_status_counts"], {"ready_to_draft": 1})
        self.assertEqual(summary["failures"], [])

    def test_no_msgaudit_scan_health_poc_fails_on_stale_heartbeat(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_scan_health_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "desktop_scan_log.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "type": "scan_heartbeat",
                        "iteration": 1,
                        "captured_at": "2026-05-18T10:00:00+08:00",
                        "snapshot_ref": "",
                        "send_plan_count": 0,
                        "status": "idle",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--log-jsonl",
                    str(log_path),
                    "--now",
                    "2026-05-18T10:02:00+08:00",
                    "--max-heartbeat-age-seconds",
                    "30",
                ],
                text=True,
                capture_output=True,
            )

        summary = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["last_heartbeat_age_seconds"], 120)
        self.assertIn("stale_heartbeat", summary["failures"])

    def test_no_msgaudit_trial_report_poc_accepts_stable_dry_run_log(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_trial_report_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            log_path = tmp_path / "desktop_scan_log.jsonl"
            targets_path = tmp_path / "targets.json"
            targets_path.write_text(
                json.dumps(
                    [
                        {
                            "roomid": "wr_auto_loan_group",
                            "chat_name": "汽车贷款小助手",
                            "enabled": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "scan_heartbeat",
                                "iteration": 1,
                                "captured_at": "2026-05-18T10:00:00+08:00",
                                "snapshot_ref": "/tmp/wecom/001.txt",
                                "send_plan_count": 0,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "wecom_event",
                                "event_id": "ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                                "chat_name": "汽车贷款小助手",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_plan",
                                "job_id": "reply:ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                                "event_id": "ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                                "chat_name": "汽车贷款小助手",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_preflight",
                                "job_id": "reply:ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                                "event_id": "ax:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
                                "status": "ready_to_draft",
                                "failures": [],
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "scan_heartbeat",
                                "iteration": 2,
                                "captured_at": "2026-05-18T10:01:10+08:00",
                                "snapshot_ref": "/tmp/wecom/002.txt",
                                "send_plan_count": 1,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--log-jsonl",
                    str(log_path),
                    "--group-targets-json",
                    str(targets_path),
                    "--min-duration-seconds",
                    "60",
                    "--min-heartbeat-count",
                    "2",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["duration_seconds"], 70)
        self.assertEqual(report["heartbeat_count"], 2)
        self.assertEqual(report["send_plan_count"], 1)
        self.assertEqual(report["ready_preflight_count"], 1)
        self.assertEqual(report["duplicate_send_plan_event_ids"], [])
        self.assertEqual(report["failures"], [])

    def test_no_msgaudit_trial_report_poc_fails_on_duplicate_send_plan_and_unknown_chat(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_trial_report_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            log_path = tmp_path / "desktop_scan_log.jsonl"
            targets_path = tmp_path / "targets.json"
            targets_path.write_text(
                json.dumps(
                    [
                        {
                            "roomid": "wr_auto_loan_group",
                            "chat_name": "汽车贷款小助手",
                            "enabled": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "scan_heartbeat",
                                "iteration": 1,
                                "captured_at": "2026-05-18T10:00:00+08:00",
                                "snapshot_ref": "/tmp/wecom/001.txt",
                                "send_plan_count": 2,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_plan",
                                "job_id": "reply:duplicate-1",
                                "event_id": "duplicate-event",
                                "chat_name": "未授权群",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_plan",
                                "job_id": "reply:duplicate-2",
                                "event_id": "duplicate-event",
                                "chat_name": "未授权群",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "send_preflight",
                                "job_id": "reply:duplicate-1",
                                "event_id": "duplicate-event",
                                "status": "blocked",
                                "failures": ["current_chat_mismatch"],
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--log-jsonl",
                    str(log_path),
                    "--group-targets-json",
                    str(targets_path),
                    "--min-duration-seconds",
                    "0",
                    "--min-heartbeat-count",
                    "1",
                ],
                text=True,
                capture_output=True,
            )

        report = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["duplicate_send_plan_event_ids"], ["duplicate-event"])
        self.assertEqual(report["unknown_send_plan_chats"], ["未授权群"])
        self.assertIn("duplicate_send_plan_event_id", report["failures"])
        self.assertIn("unknown_send_plan_chat", report["failures"])
        self.assertIn("send_plan_without_ready_preflight", report["failures"])

    def test_no_msgaudit_desktop_trial_runner_poc_creates_evidence_bundle(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_desktop_trial_runner_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            trial_dir = tmp_path / "trial"
            source_path = tmp_path / "source_ax.txt"
            targets_path = tmp_path / "targets.json"
            targets_path.write_text(
                json.dumps(
                    [
                        {
                            "roomid": "wr_auto_loan_group",
                            "chat_name": "汽车贷款小助手",
                            "enabled": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source_path.write_text(
                "\n".join(
                    [
                        "AXApplication 企业微信",
                        "  AXWindow 企业微信",
                        "    AXRow (selected)",
                        "      AXCell (selected)",
                        "        AXStaticText 汽车贷款小助手",
                        "    AXTextField 汽车贷款小助手",
                        "    AXScrollArea",
                        "      AXTable",
                        "        AXRow",
                        "          AXCell",
                        "            AXStaticText 16:48",
                        "            AXStaticText sky",
                        "            AXTextArea 需要经营证明吗 @刘红利",
                        "    AXTextArea",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--trial-dir",
                    str(trial_dir),
                    "--assistant-name",
                    "刘红利",
                    "--group-targets-json",
                    str(targets_path),
                    "--capture-source-text-file",
                    str(source_path),
                    "--capture-iterations",
                    "1",
                    "--scan-iterations",
                    "1",
                    "--capture-interval-seconds",
                    "0",
                    "--scan-interval-seconds",
                    "0",
                    "--min-duration-seconds",
                    "0",
                    "--min-heartbeat-count",
                    "1",
                    "--health-max-heartbeat-age-seconds",
                    "60",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            summary = json.loads(result.stdout)
            health_report = json.loads((trial_dir / "health_report.json").read_text(encoding="utf-8"))
            trial_report = json.loads((trial_dir / "trial_report.json").read_text(encoding="utf-8"))
            scan_rows = [
                json.loads(line)
                for line in (trial_dir / "desktop_scan_log.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            snapshot_dir_exists = Path(summary["snapshot_dir"]).exists()
            scan_log_exists = Path(summary["scan_log"]).exists()

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["type"], "desktop_trial_summary")
        self.assertEqual(summary["capture_returncode"], 0)
        self.assertEqual(summary["scan_returncode"], 0)
        self.assertTrue(summary["health_ok"])
        self.assertTrue(summary["trial_ok"])
        self.assertTrue(snapshot_dir_exists)
        self.assertTrue(scan_log_exists)
        self.assertTrue(health_report["ok"])
        self.assertTrue(trial_report["ok"])
        self.assertEqual(trial_report["send_plan_count"], 1)
        self.assertTrue(any(row["type"] == "wecom_event" for row in scan_rows))

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
