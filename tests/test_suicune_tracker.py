from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest


os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from suicune_tracker import DragBar  # noqa: E402


class FakeWindowHandle:
    def __init__(self) -> None:
        self.system_move_calls = 0

    def startSystemMove(self) -> bool:
        self.system_move_calls += 1
        return True


class DragBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_mouse_press_delegates_drag_to_window_system(self) -> None:
        window = QWidget()
        window.resize(200, 100)
        bar = DragBar(window)
        bar.resize(200, 40)
        window.show()
        self.app.processEvents()

        handle = FakeWindowHandle()
        window.windowHandle = lambda: handle
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=bar.rect().center())
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=bar.rect().center())
        window.close()

        self.assertEqual(handle.system_move_calls, 1)


@unittest.skipIf(os.name == "nt", "POSIX SIGINT subprocess behavior")
class InterruptTests(unittest.TestCase):
    def test_sigint_exits_without_traceback(self) -> None:
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "suicune_tracker.py")],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        try:
            time.sleep(0.8)
            process.send_signal(signal.SIGINT)
            _stdout, stderr = process.communicate(timeout=3)
        except BaseException:
            process.kill()
            process.communicate()
            raise

        self.assertEqual(process.returncode, 0, stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("KeyboardInterrupt", stderr)


if __name__ == "__main__":
    unittest.main()
