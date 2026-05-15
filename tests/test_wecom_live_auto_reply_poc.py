import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
