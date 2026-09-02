from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from stzy_app.ui.state import UiState


class UiStateTest(unittest.TestCase):
    def test_log_is_ui_only_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            state = UiState()
            output = io.StringIO()

            with redirect_stdout(output):
                state.log("任务日志")

        self.assertEqual(output.getvalue(), "")
        self.assertIn("任务日志", state.snapshot()[0][0])

    def test_log_prints_to_console_when_enabled(self) -> None:
        with patch.dict("os.environ", {"STZY_CONSOLE_LOG": "1"}, clear=True):
            state = UiState()
            output = io.StringIO()

            with redirect_stdout(output):
                state.log("任务日志")

        self.assertIn("任务日志", output.getvalue())
        self.assertIn("任务日志", state.snapshot()[0][0])


if __name__ == "__main__":
    unittest.main()
