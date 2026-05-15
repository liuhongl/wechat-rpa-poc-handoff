import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.wecom_live_auto_reply_poc as live_auto_reply


class WecomLiveAutoReplyPocTests(unittest.TestCase):
    def test_run_osascript_surfaces_stderr(self) -> None:
        error = subprocess.CalledProcessError(
            1,
            ["osascript"],
            stderr="execution error: osascript 不允许辅助访问 (-1719)",
        )

        with patch.object(live_auto_reply.sys, "platform", "darwin"):
            with patch.object(live_auto_reply.subprocess, "run", side_effect=error):
                with self.assertRaises(SystemExit) as raised:
                    live_auto_reply._run_osascript("bad script")

        self.assertIn("不允许辅助访问", str(raised.exception))

    def test_read_wecom_ui_text_rejects_empty_accessibility_tree(self) -> None:
        with patch.object(live_auto_reply, "_run_osascript", return_value="\n"):
            with self.assertRaises(SystemExit) as raised:
                live_auto_reply._read_wecom_ui_text("企业微信")

        self.assertIn("no accessible UI text", str(raised.exception))

    def test_mark_planned_records_manual_send_state_without_desktop_run(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "wecom_live_auto_reply_poc.py"
        fixture = root / "tests" / "fixtures" / "wecom_ui_live_mentions.txt"

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "processed.json"
            out_file = Path(tmpdir) / "actions.jsonl"
            base_command = [
                sys.executable,
                str(script),
                "--ui-text-file",
                str(fixture),
                "--chat-name",
                "汽车贷款小助手",
                "--assistant-name",
                "刘红利",
                "--state-file",
                str(state_file),
                "--out",
                str(out_file),
            ]

            first = subprocess.run(
                [*base_command, "--mark-planned"],
                text=True,
                capture_output=True,
                check=True,
            )
            second = subprocess.run(
                base_command,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn('"sender": "sky"', first.stdout)
        self.assertIn("[live-ui-auto-reply] no pending reply actions", second.stdout)


if __name__ == "__main__":
    unittest.main()
