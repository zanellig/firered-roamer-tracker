"""Desktop tracker behavior tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QMenu,
    QWidget,
)

from main import (  # noqa: E402
    CLASSIC_UI,
    TOWN_MAP_UI,
    DragBar,
    KWinPinController,
    TownMapView,
    TrackerWindow,
    normalize_ui_layout,
    stored_ui_layout,
)
from tracker import (  # noqa: E402
    EMERALD,
    ENTEI,
    FIRERED,
    LATIAS,
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
        message_type: object,
        arguments: list[object] | None = None,
    ) -> None:
        self.message_type = message_type
        self.reply_arguments = arguments or []

    def type(self) -> object:
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
    REPLY_MESSAGE = object()
    ERROR_MESSAGE = object()

    @staticmethod
    def reply(arguments: list[object] | None = None) -> FakeDBusReply:
        return FakeDBusReply(
            KWinPinControllerTests.REPLY_MESSAGE,
            arguments,
        )

    def test_invokes_an_available_kwin_shortcut(self) -> None:
        interface = FakeDBusInterface(
            [
                self.reply([[KWinPinController.SHORTCUT, "Window Close"]]),
                self.reply(),
            ]
        )
        controller = KWinPinController(interface, self.REPLY_MESSAGE)

        self.assertTrue(controller.toggle())
        self.assertEqual(
            interface.calls,
            [
                ("shortcutNames",),
                ("invokeShortcut", KWinPinController.SHORTCUT),
            ],
        )

    def test_returns_false_when_the_shortcut_is_missing(self) -> None:
        interface = FakeDBusInterface([self.reply([["Window Close"]])])
        controller = KWinPinController(interface, self.REPLY_MESSAGE)

        self.assertFalse(controller.toggle())
        self.assertEqual(interface.calls, [("shortcutNames",)])

    def test_returns_false_when_the_shortcut_query_fails(self) -> None:
        interface = FakeDBusInterface([FakeDBusReply(self.ERROR_MESSAGE)])
        controller = KWinPinController(interface, self.REPLY_MESSAGE)

        self.assertFalse(controller.toggle())
        self.assertEqual(interface.calls, [("shortcutNames",)])

    def test_returns_false_when_the_shortcut_invocation_fails(self) -> None:
        interface = FakeDBusInterface(
            [
                self.reply([[KWinPinController.SHORTCUT]]),
                FakeDBusReply(self.ERROR_MESSAGE),
            ]
        )
        controller = KWinPinController(interface, self.REPLY_MESSAGE)

        self.assertFalse(controller.toggle())
        self.assertEqual(
            interface.calls,
            [
                ("shortcutNames",),
                ("invokeShortcut", KWinPinController.SHORTCUT),
            ],
        )

    def test_skips_dbus_on_unsupported_platforms(self) -> None:
        with patch.object(sys, "platform", "win32"):
            self.assertIsNone(KWinPinController.for_current_session())


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
        self.assertFalse(window.pin_button.icon().isNull())
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
            game=FIRERED,
            roamer=Roamer(species, roamer_location, active),
            player=player_location,
            same_area=same_area,
            forecast=forecast,
        )

    def test_centers_inline_icons_with_their_labels(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        window.show()
        self.app.processEvents()

        pairs = [
            (
                window.findChild(QLabel, "brandMark"),
                window.findChild(QLabel, "brand"),
            ),
            (window.connection_dot, window.connection_label),
            (window.match_icon, window.match_text),
        ]
        for object_name in ("playerLegend", "roamerLegend", "nextLegend"):
            icon = window.findChild(QWidget, object_name)
            self.assertIsNotNone(icon)
            label = icon.parentWidget().findChild(QLabel, "legendLabel")
            self.assertIsNotNone(label)
            pairs.append((icon, label))

        for icon, label in pairs:
            with self.subTest(icon=icon.objectName()):
                icon_top = icon.mapTo(window, icon.rect().topLeft()).y()
                label_top = label.mapTo(window, label.rect().topLeft()).y()
                icon_center = 2 * icon_top + icon.height()
                label_center = 2 * label_top + label.height()
                self.assertEqual(icon_center, label_center)

        window.close()

    def test_map_content_fills_the_inside_of_its_frame(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        window.show()
        self.app.processEvents()

        image = window.map.grab().toImage()
        edge_points = (
            (3, image.height() // 2),
            (image.width() - 4, image.height() // 2),
            (image.width() // 2, 3),
            (image.width() // 2, image.height() - 4),
        )
        for point in edge_points:
            with self.subTest(point=point):
                self.assertNotEqual(image.pixelColor(*point).name(), "#101b2d")

        window.close()

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
                self.assertEqual(
                    window.roamer_legend_label.text(), species.name.upper()
                )
                self.assertEqual(window.windowTitle(), f"Rastreador de {species.name}")
                self.assertFalse(window.roamer_sprite.pixmap().isNull())

        window.close()

    def test_switches_to_emerald_species_and_the_hoenn_map(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )
        roamer_location = location_for(0, 34, EMERALD)
        player_location = location_for(0, 4, EMERALD)
        snapshot = TrackerSnapshot(
            game=EMERALD,
            roamer=Roamer(LATIAS, roamer_location, True),
            player=player_location,
            same_area=False,
            forecast=forecast_movement(
                roamer_location,
                player_location,
                location_for(0, 25, EMERALD),
                EMERALD,
            ),
        )

        window.show_snapshot(snapshot)

        self.assertEqual(window.brand.text(), "RASTREADOR  /  HOENN")
        self.assertIn("Hoenn", window.map.accessibleName())
        self.assertEqual(window.roamer_heading.text(), "LATIAS")
        self.assertEqual(window.roamer_location.text(), "Ruta 119")
        self.assertFalse(window.roamer_sprite.pixmap().isNull())
        self.assertFalse(window.map.grab().toImage().isNull())
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
        window.show_snapshot(self.snapshot(SUICUNE, roamer_map=27, player_map=27))

        self.assertEqual(window.match_text.text(), "¡MISMA ZONA!")
        self.assertEqual(window.match_hint.text(), "")
        window.close()


class FakeSettings:
    """Stand-in for QSettings: the tracker only ever touches one key."""

    def __init__(self, stored: object) -> None:
        self.stored = stored

    def value(self, _key: str) -> object:
        return self.stored

    def setValue(self, _key: str, value: object) -> None:
        self.stored = value


class UiLayoutSettingsTests(unittest.TestCase):
    def test_keeps_a_remembered_layout(self) -> None:
        self.assertEqual(stored_ui_layout(FakeSettings(TOWN_MAP_UI)), TOWN_MAP_UI)
        self.assertEqual(stored_ui_layout(FakeSettings("  MAPA  ")), TOWN_MAP_UI)

    def test_falls_back_when_the_settings_file_was_edited(self) -> None:
        for stored in (None, "", "otro", 5, ["mapa"]):
            with self.subTest(stored=stored):
                self.assertIsNone(normalize_ui_layout(stored))
                self.assertEqual(stored_ui_layout(FakeSettings(stored)), CLASSIC_UI)

    def test_rejects_an_unknown_layout(self) -> None:
        with self.assertRaises(ValueError):
            TrackerWindow(
                "127.0.0.1",
                55355,
                0.2,
                ui="otro",
                start_worker=False,
                pin_controller=None,
            )


class SettingsMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def layout_actions(window: TrackerWindow) -> list[QAction]:
        menu = window.settings_button.findChild(QMenu)
        return [action for action in menu.actions() if action.isCheckable()]

    def test_menu_switches_the_layout_and_remembers_it(self) -> None:
        settings = FakeSettings(CLASSIC_UI)
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
            settings=settings,
        )
        window.show()

        actions = self.layout_actions(window)
        self.assertEqual(
            [action.text() for action in actions], ["Clásica", "Mapa regional"]
        )
        self.assertEqual([action.isChecked() for action in actions], [True, False])

        actions[1].trigger()
        QTest.qWait(20)

        self.assertIsInstance(window.town_map, TownMapView)
        self.assertEqual(window.size().toTuple(), TownMapView.SIZE)
        self.assertEqual(settings.stored, TOWN_MAP_UI)
        self.assertEqual(
            [action.isChecked() for action in self.layout_actions(window)],
            [False, True],
        )

        self.layout_actions(window)[0].trigger()
        QTest.qWait(20)

        self.assertIsNone(window.town_map)
        self.assertEqual(window.size().toTuple(), (512, 680))
        self.assertEqual(settings.stored, CLASSIC_UI)
        window.close()

    def test_switching_keeps_the_state_the_window_is_showing(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            ui=TOWN_MAP_UI,
            start_worker=False,
            pin_controller=None,
            settings=FakeSettings(TOWN_MAP_UI),
        )
        window.show()
        window.show_connection(True)
        window.show_snapshot(TownMapViewTests.snapshot())
        window.pin_button.setChecked(False)

        self.layout_actions(window)[0].trigger()
        QTest.qWait(20)

        self.assertEqual(window.roamer_location.text(), "Ruta 22")
        self.assertEqual(window.connection_label.text(), "EN VIVO")
        self.assertFalse(window.pin_button.isChecked())
        window.close()


class TownMapViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def town_map_window(self) -> TrackerWindow:
        return TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            ui=TOWN_MAP_UI,
            start_worker=False,
            pin_controller=None,
        )

    @staticmethod
    def snapshot(
        *,
        active: bool = True,
        roamer_map: int = 41,
        player_map: int = 1,
        history_exclusion_map: int = 19,
    ) -> TrackerSnapshot:
        roamer_location = location_for(3, roamer_map)
        player_location = location_for(3, player_map)
        return TrackerSnapshot(
            game=FIRERED,
            roamer=Roamer(SUICUNE, roamer_location, active),
            player=player_location,
            same_area=active and roamer_map == player_map,
            forecast=(
                forecast_movement(
                    roamer_location,
                    player_location,
                    location_for(3, history_exclusion_map),
                )
                if active
                else None
            ),
        )

    def test_builds_the_town_map_layout_instead_of_the_panels(self) -> None:
        window = self.town_map_window()

        self.assertIsInstance(window.town_map, TownMapView)
        self.assertEqual(window.size().toTuple(), TownMapView.SIZE)
        window.close()

    def test_classic_layout_stays_the_default(self) -> None:
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            start_worker=False,
            pin_controller=None,
        )

        self.assertIsNone(window.town_map)
        self.assertEqual(window.size().toTuple(), (512, 680))
        window.close()

    def test_scripts_the_message_box_for_each_situation(self) -> None:
        window = self.town_map_window()
        view = window.town_map

        self.assertEqual(view.pages(), ["Buscando el juego…"])

        window.show_snapshot(self.snapshot(active=False))
        self.assertIn("todavía no recorre KANTO", view.pages()[0])

        window.show_snapshot(self.snapshot(roamer_map=1))
        self.assertIn("misma zona", view.pages()[0])

        window.show_snapshot(self.snapshot())
        script = view.pages()
        self.assertIn("SUICUNE está en RUTA 22.", script[0])
        self.assertIn("RUTA 2 47,1%", script[1])
        self.assertIn("¡Cruzá a RUTA 2 ahora!", script[2])

        # Ruta 16 with the player in Fuchsia has no immediate crossing, so the
        # script keeps the odds and adds no interception page.
        window.show_snapshot(self.snapshot(roamer_map=34, player_map=7))
        self.assertEqual(len(view.pages()), 2)
        window.close()

    def test_cycles_through_every_page_of_the_script(self) -> None:
        window = self.town_map_window()
        view = window.town_map
        window.show_snapshot(self.snapshot())

        script = view.pages()
        self.assertEqual(len(script), 3)
        seen = [view.current_page()]
        for _ in range(len(script)):
            view._turn_page()
            seen.append(view.current_page())

        self.assertEqual(seen[0], seen[-1])
        self.assertEqual(set(seen), set(script))
        window.close()

    def test_paints_every_situation_without_an_empty_script(self) -> None:
        window = self.town_map_window()
        view = window.town_map
        window.show()

        situations = (
            None,
            self.snapshot(active=False),
            self.snapshot(roamer_map=1),
            self.snapshot(),
        )
        for snapshot in situations:
            with self.subTest(snapshot=snapshot):
                if snapshot is not None:
                    window.show_snapshot(snapshot)
                self.assertTrue(view.pages())
                self.assertIn(view.current_page(), view.pages())
                self.assertFalse(window.grab().toImage().isNull())
        window.close()

    def test_reports_the_species_in_the_window_handle(self) -> None:
        window = self.town_map_window()
        window.show_snapshot(self.snapshot())

        self.assertEqual(window.windowTitle(), "Rastreador de Suicune")
        self.assertFalse(window.windowIcon().isNull())
        window.close()

    def test_pin_button_drives_the_window(self) -> None:
        controller = FakePinController()
        window = TrackerWindow(
            "127.0.0.1",
            55355,
            0.2,
            ui=TOWN_MAP_UI,
            start_worker=False,
            pin_controller=controller,
        )
        window.show()
        QTest.qWait(20)

        self.assertEqual(controller.toggle_calls, 1)
        QTest.mouseClick(window.pin_button, Qt.MouseButton.LeftButton)
        self.assertEqual(controller.toggle_calls, 2)
        window.close()


class CloseButtonTests(unittest.TestCase):
    def test_close_button_exits_the_application(self) -> None:
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(ROOT / "src")!r})

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QToolButton
            from main import TrackerWindow

            app = QApplication([])
            window = TrackerWindow(
                "127.0.0.1",
                55355,
                0.2,
                start_worker=False,
                pin_controller=None,
            )
            window.show()
            close_button = window.findChild(QToolButton, "closeButton")
            QTimer.singleShot(0, close_button.click)
            QTimer.singleShot(300, lambda: app.exit(7))
            raise SystemExit(app.exec())
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=3,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


@unittest.skipIf(os.name == "nt", "POSIX SIGINT subprocess behavior")
class InterruptTests(unittest.TestCase):
    def test_sigint_exits_without_traceback(self) -> None:
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "main.py")],
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
