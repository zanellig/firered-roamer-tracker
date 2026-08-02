"""Desktop tracker behavior tests."""

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
from PySide6.QtDBus import QDBusMessage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from roamer_tracker import DragBar, KWinPinController, TrackerWindow  # noqa: E402
from tracker import (  # noqa: E402
    ENTEI,
    RAIKOU,
    SUICUNE,
    Roamer,
    TrackerSnapshot,
    forecast_movement,
    location_for,
)


class FakeWindowHandle:
    def __init__(self) -> None:
        self.system_move_calls = 0

    def startSystemMove(self) -> bool:
        self.system_move_calls += 1
        return True


class FakePinController:
    def __init__(self) -> None:
        self.toggle_calls = 0

    def toggle(self) -> bool:
        self.toggle_calls += 1
        return True


class FakeDBusReply:
    def __init__(
        self,
        message_type: QDBusMessage.MessageType,
        arguments: list[object] | None = None,
    ) -> None:
        self.message_type = message_type
        self.reply_arguments = arguments or []

    def type(self) -> QDBusMessage.MessageType:
        return self.message_type

    def arguments(self) -> list[object]:
        return self.reply_arguments


class FakeDBusInterface:
    def __init__(self, replies: list[FakeDBusReply]) -> None:
        self.replies = replies
        self.calls: list[tuple[object, ...]] = []

    def call(self, *arguments: object) -> FakeDBusReply:
        self.calls.append(arguments)
        return self.replies.pop(0)


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


class KWinPinControllerTests(unittest.TestCase):
    @staticmethod
    def reply(arguments: list[object] | None = None) -> FakeDBusReply:
        return FakeDBusReply(
            QDBusMessage.MessageType.ReplyMessage,
            arguments,
        )

    def test_invokes_an_available_kwin_shortcut(self) -> None:
        interface = FakeDBusInterface(
            [
                self.reply([[KWinPinController.SHORTCUT, "Window Close"]]),
                self.reply(),
            ]
        )
        controller = KWinPinController(interface)

        self.assertTrue(controller.toggle())
        self.assertEqual(
            interface.calls,
            [
                ("shortcutNames",),
                ("invokeShortcut", KWinPinController.SHORTCUT),
            ],
        )

    def test_returns_false_when_the_shortcut_is_missing(self) -> None:
        interface = FakeDBusInterface(
            [self.reply([["Window Close"]])]
        )
        controller = KWinPinController(interface)

        self.assertFalse(controller.toggle())
        self.assertEqual(interface.calls, [("shortcutNames",)])

    def test_returns_false_when_the_shortcut_query_fails(self) -> None:
        interface = FakeDBusInterface(
            [FakeDBusReply(QDBusMessage.MessageType.ErrorMessage)]
        )
        controller = KWinPinController(interface)

        self.assertFalse(controller.toggle())
        self.assertEqual(interface.calls, [("shortcutNames",)])

    def test_returns_false_when_the_shortcut_invocation_fails(self) -> None:
        interface = FakeDBusInterface(
            [
                self.reply([[KWinPinController.SHORTCUT]]),
                FakeDBusReply(QDBusMessage.MessageType.ErrorMessage),
            ]
        )
        controller = KWinPinController(interface)

        self.assertFalse(controller.toggle())
        self.assertEqual(
            interface.calls,
            [
                ("shortcutNames",),
                ("invokeShortcut", KWinPinController.SHORTCUT),
            ],
        )


class PinButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_native_controller_handles_initial_pin_and_button_toggle(self) -> None:
        controller = FakePinController()
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=controller,
        )
        window.show()
        QTest.qWait(20)

        self.assertEqual(controller.toggle_calls, 1)
        QTest.mouseClick(window.pin_button, Qt.MouseButton.LeftButton)
        self.assertEqual(controller.toggle_calls, 2)
        self.assertTrue(window.isVisible())
        window.close()


class TrackerWindowDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def snapshot(
        species,
        *,
        active: bool = True,
        roamer_map: int = 27,
        player_map: int = 26,
        history_exclusion_map: int = 20,
    ) -> TrackerSnapshot:
        roamer_location = location_for(3, roamer_map)
        player_location = location_for(3, player_map)
        same_area = active and roamer_map == player_map
        forecast = (
            forecast_movement(
                roamer_location,
                player_location,
                location_for(3, history_exclusion_map),
            )
            if active
            else None
        )
        return TrackerSnapshot(
            roamer=Roamer(species, roamer_location, active),
            player=player_location,
            same_area=same_area,
            forecast=forecast,
        )

    def test_updates_name_sprite_and_title_for_each_roamer(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )

        for species in (RAIKOU, ENTEI, SUICUNE):
            with self.subTest(species=species.name):
                window.show_snapshot(self.snapshot(species))
                self.assertEqual(window.roamer_heading.text(), species.name.upper())
                self.assertEqual(window.roamer_legend_label.text(), species.name.upper())
                self.assertEqual(window.windowTitle(), f"Rastreador de {species.name}")
                self.assertFalse(window.roamer_sprite.pixmap().isNull())

        window.close()

    def test_shows_inactive_roamer_without_a_false_match(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        window.show_snapshot(self.snapshot(ENTEI, active=False))

        self.assertEqual(window.roamer_location.text(), "INACTIVO")
        self.assertEqual(window.match_text.text(), "El roamer no está activo")
        self.assertFalse(window.match_banner.property("matched"))
        window.close()

    def test_keeps_probabilities_without_recommending_a_reset(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        snapshot = self.snapshot(SUICUNE, roamer_map=34, player_map=7)
        window.show_snapshot(snapshot)

        self.assertIsNone(snapshot.forecast.recommendation)
        self.assertEqual(window.match_banner.property("mode"), "idle")
        self.assertEqual(window.match_text.text(), "PRÓXIMO MOVIMIENTO")
        self.assertEqual(window.match_hint.text(), "RUTAS PROBABLES EN EL MAPA")
        self.assertIn("Ruta 7 47,1%", window.match_banner.toolTip())
        window.close()

    def test_recommends_fast_cross_when_likely_route_matches_the_city(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        snapshot = self.snapshot(SUICUNE, roamer_map=23, player_map=5)
        window.show_snapshot(snapshot)

        self.assertIsNotNone(snapshot.forecast.recommendation)
        self.assertEqual(window.match_banner.property("mode"), "cross")
        self.assertEqual(window.match_text.text(), "CRUZÁ A RUTA 6 · 15,9%")
        window.close()

    def test_recommends_route_2_from_viridian_after_route_1(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        snapshot = self.snapshot(
            SUICUNE,
            roamer_map=41,
            player_map=1,
            history_exclusion_map=19,
        )
        window.show_snapshot(snapshot)

        self.assertEqual(window.match_banner.property("mode"), "cross")
        self.assertEqual(window.match_text.text(), "CRUZÁ A RUTA 2 · 47,1%")
        self.assertIn("Ruta 23 47,1%", window.match_banner.toolTip())
        window.close()

    def test_same_area_message_has_no_redundant_instruction(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        window.show_snapshot(
            self.snapshot(SUICUNE, roamer_map=27, player_map=27)
        )

        self.assertEqual(window.match_text.text(), "¡MISMA ZONA!")
        self.assertEqual(window.match_hint.text(), "")
        window.close()


@unittest.skipIf(os.name == "nt", "POSIX SIGINT subprocess behavior")
class InterruptTests(unittest.TestCase):
    def test_sigint_exits_without_traceback(self) -> None:
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "roamer_tracker.py")],
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
