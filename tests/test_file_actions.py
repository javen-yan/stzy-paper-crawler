from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stzy_app.local import choose_directory, open_path


class FileActionTest(unittest.TestCase):
    def test_windows_open_path_uses_nonblocking_cmd_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            with (
                patch("stzy_app.local.platform.system", return_value="Windows"),
                patch("stzy_app.local.os.startfile", create=True) as startfile,
            ):
                self.assertTrue(open_path(target))

        startfile.assert_called_once_with(str(target))

    def test_open_path_returns_false_when_system_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("stzy_app.local.platform.system", return_value="Windows"),
                patch("stzy_app.local.os.startfile", side_effect=OSError, create=True),
            ):
                self.assertFalse(open_path(Path(tmpdir)))

    def test_macos_folder_picker_escapes_quotes_in_initial_path(self) -> None:
        with (
            patch("stzy_app.local.platform.system", return_value="Darwin"),
            patch("stzy_app.local.Path.home", return_value=Path('/tmp/a "quoted" dir')),
            patch("stzy_app.local.subprocess.run") as run,
        ):
            run.return_value.returncode = 1
            run.return_value.stdout = ""

            self.assertIsNone(choose_directory(Path("/path/that/does/not/exist")))

        script = run.call_args.args[0][2]
        self.assertIn('/tmp/a \\"quoted\\" dir', script)

    def test_folder_picker_failure_returns_none(self) -> None:
        with (
            patch("stzy_app.local.platform.system", return_value="Windows"),
            patch("stzy_app.local._choose_directory_tk", side_effect=RuntimeError),
        ):
            self.assertIsNone(choose_directory(Path("C:/downloads")))

    def test_linux_folder_picker_without_display_returns_none(self) -> None:
        with (
            patch("stzy_app.local.platform.system", return_value="Linux"),
            patch.dict(
                "stzy_app.local.os.environ",
                {"DISPLAY": "", "WAYLAND_DISPLAY": ""},
                clear=True,
            ),
            patch("stzy_app.local._choose_directory_tk") as tk_picker,
        ):
            self.assertIsNone(choose_directory(Path("/tmp/downloads")))

        tk_picker.assert_not_called()
