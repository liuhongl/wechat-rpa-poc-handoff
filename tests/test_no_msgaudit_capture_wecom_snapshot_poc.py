import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.no_msgaudit_capture_wecom_snapshot_poc as capture_poc


class NoMsgAuditCaptureWeComSnapshotPocTests(unittest.TestCase):
    def test_run_osascript_surfaces_stderr(self) -> None:
        error = subprocess.CalledProcessError(
            1,
            ["osascript"],
            stderr="execution error: osascript 不允许辅助访问 (-1719)",
        )

        with patch.object(capture_poc.sys, "platform", "darwin"):
            with patch.object(capture_poc.subprocess, "run", side_effect=error):
                with self.assertRaises(SystemExit) as raised:
                    capture_poc._run_osascript("bad script")

        self.assertIn("不允许辅助访问", str(raised.exception))

    def test_read_wecom_accessibility_tree_rejects_empty_output(self) -> None:
        with patch.object(capture_poc, "_run_osascript", return_value="\n"):
            with self.assertRaises(SystemExit) as raised:
                capture_poc._read_wecom_accessibility_tree("企业微信", capture_method="applescript")

        self.assertIn("no accessible UI tree", str(raised.exception))

    def test_run_swift_ax_probe_surfaces_stderr(self) -> None:
        error = subprocess.CalledProcessError(
            1,
            ["swift", "probe.swift", "企业微信"],
            stderr="AX permission denied",
        )

        with patch.object(capture_poc.sys, "platform", "darwin"):
            with patch.object(capture_poc.subprocess, "run", side_effect=error):
                with self.assertRaises(SystemExit) as raised:
                    capture_poc._run_swift_ax_probe("企业微信")

        self.assertIn("AX permission denied", str(raised.exception))

    def test_read_wecom_accessibility_tree_rejects_empty_swift_output(self) -> None:
        with patch.object(capture_poc, "_run_swift_ax_probe", return_value="\n"):
            with self.assertRaises(SystemExit) as raised:
                capture_poc._read_wecom_accessibility_tree("企业微信", capture_method="swift-ax")

        self.assertIn("no accessible UI tree", str(raised.exception))

    def test_read_wecom_accessibility_tree_rejects_unknown_method(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            capture_poc._read_wecom_accessibility_tree("企业微信", capture_method="unknown")

        self.assertIn("unknown capture method", str(raised.exception))

    def test_capture_script_writes_source_text_file_to_snapshot_dir(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_capture_wecom_snapshot_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "source.txt"
            snapshot_dir = tmp_path / "snapshots"
            source.write_text(
                "83 文本栏 (settable, string) 汽车金融VIP群\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source-text-file",
                    str(source),
                    "--snapshot-dir",
                    str(snapshot_dir),
                    "--captured-at",
                    "2026-05-17T10:00:00+08:00",
                    "--prefix",
                    "wecom-live",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            written_path = Path(payload["path"])

            self.assertTrue(written_path.exists())
            self.assertTrue(written_path.name.startswith("wecom-live-20260517T100000"))
            self.assertEqual(
                written_path.read_text(encoding="utf-8"),
                "83 文本栏 (settable, string) 汽车金融VIP群\n",
            )
            self.assertEqual(payload["source"], "source_text_file")
            self.assertGreater(payload["bytes"], 0)

    def test_capture_script_can_write_multiple_iterations_without_overwriting(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "no_msgaudit_capture_wecom_snapshot_poc.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "source.txt"
            snapshot_dir = tmp_path / "snapshots"
            source.write_text(
                "83 文本栏 (settable, string) 汽车金融VIP群\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source-text-file",
                    str(source),
                    "--snapshot-dir",
                    str(snapshot_dir),
                    "--captured-at",
                    "2026-05-17T10:00:00+08:00",
                    "--prefix",
                    "wecom-live",
                    "--iterations",
                    "2",
                    "--interval-seconds",
                    "0",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            payloads = [json.loads(line) for line in result.stdout.splitlines()]
            paths = [Path(payload["path"]) for payload in payloads]

            self.assertEqual(len(payloads), 2)
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue(paths[0].name.startswith("wecom-live-20260517T100000-001"))
            self.assertTrue(paths[1].name.startswith("wecom-live-20260517T100000-002"))
            self.assertTrue(paths[0].exists())
            self.assertTrue(paths[1].exists())
            self.assertEqual(payloads[0]["iteration"], 1)
            self.assertEqual(payloads[1]["iteration"], 2)


if __name__ == "__main__":
    unittest.main()
