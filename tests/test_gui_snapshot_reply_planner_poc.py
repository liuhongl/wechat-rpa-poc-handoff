import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GuiSnapshotReplyPlannerPocTests(unittest.TestCase):
    def test_plans_reply_jobs_from_gui_snapshot_without_msgaudit(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "gui_snapshot_reply_planner_poc.py"

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

        self.assertIn('"chat_name": "汽车贷款小助手"', result.stdout)
        self.assertIn('"chat_name": "汽车金融VIP群"', result.stdout)
        self.assertNotIn("暂停自动回复群", result.stdout)
        self.assertNotIn("未配置群", result.stdout)

    def test_mark_planned_skips_same_gui_snapshot_records(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "gui_snapshot_reply_planner_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            base_command = [
                sys.executable,
                str(script),
                "--assistant-name",
                "刘红利",
                "--state-file",
                str(state_file),
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

        self.assertIn('"chat_name": "汽车贷款小助手"', first.stdout)
        self.assertIn("[gui-snapshot-reply] no pending reply jobs", second.stdout)


if __name__ == "__main__":
    unittest.main()
