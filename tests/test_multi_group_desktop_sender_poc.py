import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MultiGroupDesktopSenderPocTests(unittest.TestCase):
    def test_sender_plans_jobs_without_running_desktop(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "multi_group_desktop_sender_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_path = Path(tmpdir) / "jobs.jsonl"
            out_path = Path(tmpdir) / "send_plans.jsonl"
            jobs_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source_msgid": "msg-1",
                                "roomid": "wr_1",
                                "chat_name": "汽车贷款小助手",
                                "reply_content": "回复一",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "source_msgid": "msg-2",
                                "roomid": "wr_2",
                                "chat_name": "汽车金融VIP群",
                                "reply_content": "回复二",
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
                    "--reply-jobs-jsonl",
                    str(jobs_path),
                    "--max-jobs",
                    "10",
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn('"chat_name": "汽车贷款小助手"', result.stdout)
        self.assertIn('"chat_name": "汽车金融VIP群"', result.stdout)
        self.assertIn('"will_run": false', result.stdout)
        self.assertIn('"send": false', result.stdout)

    def test_sender_caps_jobs_and_can_include_clipboard_applescript(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "multi_group_desktop_sender_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_path = Path(tmpdir) / "jobs.jsonl"
            jobs_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source_msgid": "msg-1",
                                "roomid": "wr_1",
                                "chat_name": "汽车贷款小助手",
                                "reply_content": "回复一",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "source_msgid": "msg-2",
                                "roomid": "wr_2",
                                "chat_name": "汽车金融VIP群",
                                "reply_content": "回复二",
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
                    "--reply-jobs-jsonl",
                    str(jobs_path),
                    "--max-jobs",
                    "1",
                    "--include-applescript",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

        first_row = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(first_row["source_msgid"], "msg-1")
        self.assertNotIn('"source_msgid": "msg-2"', result.stdout)
        self.assertIn('keystroke "v" using command down', first_row["applescript"])
        self.assertIn('set targetChat to "汽车贷款小助手"', first_row["applescript"])


if __name__ == "__main__":
    unittest.main()
