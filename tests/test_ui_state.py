from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from stzy_app.crawler import CrawlStats
from stzy_app.models import ResourceRecord, ResourceStatus
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

    def test_stop_request_is_cleared_when_task_finishes(self) -> None:
        state = UiState()

        state.request_stop()
        self.assertTrue(state.snapshot()[5])

        state.progress(CrawlStats(running=False))

        self.assertFalse(state.snapshot()[5])

    def test_record_updates_existing_resource_row(self) -> None:
        state = UiState()
        record = ResourceRecord(
            resource_id="paper-1",
            resource_name="试卷",
            status=ResourceStatus.downloading,
        )
        state.record(record)

        record.status = ResourceStatus.completed
        record.image_count = 8
        state.record(record)

        rows = state.snapshot()[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(rows[0]["image_count"], 8)


if __name__ == "__main__":
    unittest.main()
