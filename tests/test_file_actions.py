from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stzy_app.ui.file_actions import open_path
from stzy_app.ui.folder_picker import choose_directory


class FileActionTest(unittest.TestCase):
    def test_windows_open_path_uses_nonblocking_cmd_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            with (
                patch("stzy_app.ui.file_actions.platform.system", return_value="Windows"),
                patch("stzy_app.ui.file_actions.subprocess.Popen") as popen,
            ):
                self.assertTrue(open_path(target))

        args = popen.call_args.args[0]
        self.assertEqual(args[:4], ["cmd", "/c", "start", ""])
        self.assertEqual(args[4], str(target))

    def test_open_path_returns_false_when_system_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("stzy_app.ui.file_actions.platform.system", return_value="Windows"),
                patch("stzy_app.ui.file_actions.subprocess.Popen", side_effect=OSError),
            ):
                self.assertFalse(open_path(Path(tmpdir)))

    def test_folder_picker_failure_returns_none(self) -> None:
        with (
            patch("stzy_app.ui.folder_picker.platform.system", return_value="Windows"),
            patch("stzy_app.ui.folder_picker._choose_directory_tk", side_effect=RuntimeError),
        ):
            self.assertIsNone(choose_directory(Path("C:/downloads")))
