import json
import subprocess
import sys
import unittest
from pathlib import Path

from app.member_assistant_poc import GroupReplyTarget, MultiGroupReplyJob
from app.no_msgaudit_desktop_agent import (
    WeComEvent,
    build_wecom_events_from_ui_snapshot,
    reply_job_to_send_plan,
    send_plan_to_dict,
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


if __name__ == "__main__":
    unittest.main()
