"""Always-on-top desktop GUI for supported GBA roaming Pokémon."""

from __future__ import annotations

import argparse
import importlib
import os
import signal
import sys
from functools import lru_cache
from pathlib import Path
from threading import Event
from typing import Protocol, cast

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup,
    QCloseEvent,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tracker import (
    ENTEI,
    FIRERED,
    LATIAS,
    LATIOS,
    RAIKOU,
    SUICUNE,
    Game,
    Location,
    RetroArchNCI,
    RoamerSpecies,
    RoamerStats,
    TrackerError,
    TrackerSnapshot,
    read_snapshot,
)

SOURCE_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = SOURCE_ROOT / "assets"
if not ASSET_ROOT.is_dir():
    ASSET_ROOT = SOURCE_ROOT.parent / "assets"
ROAMER_ASSETS = {
    RAIKOU: ASSET_ROOT / "raikou.png",
    ENTEI: ASSET_ROOT / "entei.png",
    SUICUNE: ASSET_ROOT / "suicune.png",
    LATIAS: ASSET_ROOT / "latias.png",
    LATIOS: ASSET_ROOT / "latios.png",
}

NAVY = QColor("#172640")
INK = QColor("#101b2d")
CYAN = QColor("#49b8d0")
CORAL = QColor("#e2554d")
GOLD = QColor("#f1c84b")
WHITE = QColor("#fff9e8")
MUTED = QColor("#7387a1")
LIVE = QColor("#63c79a")

# Window layouts the user can pick between. "clasica" is the panelled dark
# window; "mapa" is the GBA town-map screen.
CLASSIC_UI = "clasica"
TOWN_MAP_UI = "mapa"
UI_LAYOUTS = (CLASSIC_UI, TOWN_MAP_UI)
UI_LAYOUT_NAMES = {CLASSIC_UI: "Clásica", TOWN_MAP_UI: "Mapa regional"}
UI_SETTINGS_KEY = "ui/layout"

# Stands in for the trainer name until the game has one to read.
PLAYER_FALLBACK_NAME = "VOS"

# The roamer readouts the classic layout shows, as (key, heading, row, column).
STAT_FIELDS = (
    ("pid", "PID", 1, 0),
    ("nature", "NATURALEZA", 1, 2),
    ("hp", "PS", 2, 0),
    ("status", "ESTADO", 2, 2),
)
MISSING_STAT = "—"


def _format_probability(probability: float) -> str:
    return f"{probability:.1%}".replace(".", ",")


def player_name(snapshot: TrackerSnapshot) -> str:
    """What to call the player: their trainer name once the game shows one."""
    return snapshot.player_name or PLAYER_FALLBACK_NAME


def normalize_ui_layout(value: object) -> str | None:
    """Return a known layout name, or None when the value is not one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    return candidate if candidate in UI_LAYOUTS else None


def tracker_settings() -> QSettings:
    return QSettings("roamer-watcher", "tracker")


def stored_ui_layout(settings: QSettings) -> str:
    """Read the remembered layout, falling back when the file was edited."""
    stored = normalize_ui_layout(settings.value(UI_SETTINGS_KEY))
    return CLASSIC_UI if stored is None else stored


@lru_cache(maxsize=8)
def _scaled_sprite(path: str, size: int) -> QPixmap:
    """Cache scaled roamer sprites so repainting never touches the disk."""
    return QPixmap(path).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def _pixel_font(size: int, *, bold: bool = False) -> QFont:
    """The monospaced, unsmoothed face the GBA interface is drawn with."""
    font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
    font.setPixelSize(size)
    font.setBold(bold)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def _gba_text(
    painter: QPainter,
    rect: QRectF,
    align: Qt.AlignmentFlag,
    text: str,
    color: QColor,
    shadow: QColor,
) -> None:
    """Draw GBA-style text twice: a shadow one pixel down and right."""
    painter.setPen(shadow)
    painter.drawText(rect.translated(1, 1), align, text)
    painter.setPen(color)
    painter.drawText(rect, align, text)


def _message_box(painter: QPainter, rect: QRectF) -> None:
    """Draw the GBA dialogue frame: white slab, blue rim, thin inner rule."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 60))
    painter.drawRoundedRect(rect.translated(4, 4), 7, 7)
    painter.setBrush(QColor("#f8f8f8"))
    painter.setPen(QPen(QColor("#4870b0"), 3))
    painter.drawRoundedRect(rect, 7, 7)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#a8c0e0"), 1))
    painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 4, 4)


def _pin_pixmap(color: QColor) -> QPixmap:
    """Draw a pushpin at 4x the icon size so it stays crisp when scaled."""
    pixmap = QPixmap(60, 60)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(30, 21), 18, 18)
    painter.drawPolygon(QPolygonF([QPointF(21, 33), QPointF(39, 33), QPointF(30, 58)]))
    painter.end()
    return pixmap


def _pin_icon() -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pin_pixmap(NAVY), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_pin_pixmap(QColor("#9aabc1")), QIcon.Mode.Normal, QIcon.State.Off)
    return icon


def _settings_button(
    window: TrackerWindow, parent: QWidget | None = None
) -> QToolButton:
    """The gear that drops the settings menu, currently the layout selector."""
    button = QToolButton(parent)
    button.setObjectName("settingsButton")
    button.setText("⚙")
    button.setToolTip("Ajustes")

    menu = QMenu(button)
    # A disabled entry, not addSection(): a styled QMenu drops a section title.
    menu.addAction("Diseño de ventana").setEnabled(False)
    group = QActionGroup(menu)
    for layout in UI_LAYOUTS:
        action = menu.addAction(UI_LAYOUT_NAMES[layout])
        action.setCheckable(True)
        action.setChecked(layout == window.ui)
        group.addAction(action)
        action.triggered.connect(
            lambda _checked=False, name=layout: window.set_ui_layout(name)
        )
    # Popping the menu by hand keeps QToolButton from reserving room for its
    # own dropdown arrow, so the gear stays square like its neighbours.
    button.clicked.connect(
        lambda: menu.popup(button.mapToGlobal(QPoint(0, button.height())))
    )
    return button


class PinController(Protocol):
    def toggle(self) -> bool: ...


class _DBusReply(Protocol):
    def type(self) -> object: ...

    def arguments(self) -> list[object]: ...


class _DBusInterface(Protocol):
    def call(self, method: str, *arguments: object) -> _DBusReply: ...


class KWinPinController:
    """Toggle KWin's real keep-above state on the active Wayland window."""

    SHORTCUT = "Window Above Other Windows"

    def __init__(self, interface: _DBusInterface, reply_message_type: object) -> None:
        self.interface = interface
        self.reply_message_type = reply_message_type

    @classmethod
    def for_current_session(cls) -> KWinPinController | None:
        if sys.platform != "linux":
            return None
        app = QApplication.instance()
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
        if (
            not isinstance(app, QApplication)
            or app.platformName() != "wayland"
            or "kde" not in desktop
        ):
            return None
        try:
            qt_dbus = importlib.import_module("PySide6.QtDBus")
        except ImportError:
            return None
        interface = qt_dbus.QDBusInterface(
            "org.kde.kglobalaccel",
            "/component/kwin",
            "org.kde.kglobalaccel.Component",
            qt_dbus.QDBusConnection.sessionBus(),
        )
        if not interface.isValid():
            return None
        return cls(
            cast(_DBusInterface, interface),
            qt_dbus.QDBusMessage.MessageType.ReplyMessage,
        )

    def toggle(self) -> bool:
        shortcuts_reply = self.interface.call("shortcutNames")
        if shortcuts_reply.type() != self.reply_message_type:
            return False
        arguments = shortcuts_reply.arguments()
        if (
            len(arguments) != 1
            or not isinstance(arguments[0], list)
            or self.SHORTCUT not in arguments[0]
        ):
            return False
        reply = self.interface.call("invokeShortcut", self.SHORTCUT)
        return reply.type() == self.reply_message_type


class _AutoPinController:
    pass


AUTO_PIN_CONTROLLER = _AutoPinController()


class TrackerThread(QThread):
    """Poll RAM off the UI thread and reconnect after partial failures."""

    snapshot_ready = Signal(object)
    connection_changed = Signal(bool)

    def __init__(self, host: str, port: int, interval: float, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.port = port
        self.interval = max(interval, 0.05)
        self._stop = Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        connected: bool | None = None
        while not self._stop.is_set():
            client: RetroArchNCI | None = None
            try:
                client = RetroArchNCI(self.host, self.port)
                while not self._stop.is_set():
                    snapshot = read_snapshot(client)
                    if connected is not True:
                        connected = True
                        self.connection_changed.emit(True)
                    self.snapshot_ready.emit(snapshot)
                    if self._stop.wait(self.interval):
                        break
            except (OSError, TrackerError, ValueError):
                if connected is not False:
                    connected = False
                    self.connection_changed.emit(False)
                self._stop.wait(max(1.0, self.interval))
            finally:
                if client is not None:
                    client.close()


class DragBar(QFrame):
    """Title bar that moves its frameless top-level window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._system_move_active = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            self._drag_offset = event.globalPosition().toPoint() - window.pos()
            handle = window.windowHandle()
            if handle is not None and handle.startSystemMove():
                # Wayland does not let clients position their own top-level
                # windows. Hand the drag to the compositor while this genuine
                # mouse press still carries the required input serial.
                self._system_move_active = True
                self._drag_offset = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._system_move_active:
            event.accept()
            return
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        self._system_move_active = False
        super().mouseReleaseEvent(event)


class InlineIcon(QWidget):
    """Paint a small UI symbol around its geometric center, not a text baseline."""

    def __init__(
        self,
        kind: str,
        color: QColor,
        size: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_icon(self, kind: str, color: QColor | None = None) -> None:
        self._kind = kind
        if color is not None:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) * 0.32

        pen = QPen(self._color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._kind == "dot":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawEllipse(center, radius, radius)
        elif self._kind == "diamond":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(center.x(), center.y() - radius),
                        QPointF(center.x() + radius, center.y()),
                        QPointF(center.x(), center.y() + radius),
                        QPointF(center.x() - radius, center.y()),
                    ]
                )
            )
        elif self._kind == "route":
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(center.x() - radius, center.y() + radius * 0.45),
                        QPointF(center.x() - radius * 0.55, center.y() - radius * 0.45),
                        QPointF(center.x() + radius, center.y() - radius * 0.45),
                        QPointF(center.x() + radius * 0.55, center.y() + radius * 0.45),
                    ]
                )
            )
        elif self._kind == "double-ring":
            painter.drawEllipse(center, radius, radius)
            painter.drawEllipse(center, radius * 0.42, radius * 0.42)
        elif self._kind == "arrow":
            painter.drawLine(
                QPointF(center.x() - radius * 0.75, center.y() + radius * 0.75),
                QPointF(center.x() + radius * 0.75, center.y() - radius * 0.75),
            )
            painter.drawLine(
                QPointF(center.x() - radius * 0.05, center.y() - radius * 0.75),
                QPointF(center.x() + radius * 0.75, center.y() - radius * 0.75),
            )
            painter.drawLine(
                QPointF(center.x() + radius * 0.75, center.y() - radius * 0.75),
                QPointF(center.x() + radius * 0.75, center.y() + radius * 0.05),
            )
        elif self._kind == "dash":
            painter.drawLine(
                QPointF(center.x() - radius * 0.75, center.y()),
                QPointF(center.x() + radius * 0.75, center.y()),
            )
        else:
            painter.drawEllipse(center, radius, radius)

        painter.end()


class RegionMapWidget(QWidget):
    """Paint the active game's region map with live markers."""

    BACKDROP = INK
    FRAME = QColor("#304260")

    def __init__(self, parent=None, size: tuple[int, int] = (480, 320)) -> None:
        super().__init__(parent)
        self.setObjectName("regionMap")
        self.setFixedSize(*size)
        self._map = QPixmap()
        self._source_rect = QRectF()
        self._grid_origin = (0, 0)
        self._game: Game | None = None
        self._set_game(FIRERED)
        self._snapshot: TrackerSnapshot | None = None

    def set_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self._set_game(snapshot.game)
        self._snapshot = snapshot
        self.update()

    def player_marker(self) -> str:
        """The letter drawn on the player's marker: the trainer's initial."""
        if self._snapshot is None:
            return ""
        return player_name(self._snapshot)[0].upper()

    def _set_game(self, game: Game) -> None:
        if self._game == game:
            return
        self._game = game
        region_map = game.region_map
        self._map = QPixmap(str(ASSET_ROOT / region_map.asset_name))
        self._source_rect = QRectF(*region_map.source_rect)
        self._grid_origin = region_map.grid_origin
        self.setAccessibleName(
            f"Mapa de {region_map.name} con la ubicación del roamer y del jugador"
        )

    def _point(self, location: Location) -> tuple[float, float] | None:
        if location.map_bounds is None:
            return None
        grid_x, grid_y = location.map_bounds.center
        origin_x, origin_y = self._grid_origin
        return (8 * grid_x + origin_x + 4, 8 * grid_y + origin_y + 4)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.fillRect(self.rect(), self.BACKDROP)
        map_rect = self._map_rect()
        painter.drawPixmap(
            map_rect,
            self._map,
            self._source_rect,
        )

        painter.save()
        painter.setClipRect(map_rect)
        if self._snapshot is not None:
            if (
                self._snapshot.roamer.active
                and not self._snapshot.same_area
                and self._snapshot.forecast is not None
            ):
                self._draw_forecast(painter, self._snapshot)
            player = self._point(self._snapshot.player)
            roamer = self._point(self._snapshot.roamer.location)
            marker = self._snapshot.roamer.species.name[0]
            player_marker = self.player_marker()
            if self._snapshot.same_area and player is not None:
                self._draw_match(painter, player, marker, player_marker)
            else:
                if self._snapshot.roamer.active and roamer is not None:
                    self._draw_marker(painter, roamer, CORAL, marker, diamond=True)
                if player is not None:
                    self._draw_marker(painter, player, CYAN, player_marker)
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.FRAME, 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def _map_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(2, 2, -2, -2)

    def _scaled(self, point: tuple[float, float]) -> tuple[float, float]:
        target = self._map_rect()
        return (
            target.left()
            + (point[0] - self._source_rect.left())
            * target.width()
            / self._source_rect.width(),
            target.top()
            + (point[1] - self._source_rect.top())
            * target.height()
            / self._source_rect.height(),
        )

    def _route_rect(self, location: Location) -> QRectF | None:
        bounds = location.map_bounds
        if bounds is None:
            return None
        target = self._map_rect()
        scale_x = target.width() / self._source_rect.width()
        scale_y = target.height() / self._source_rect.height()
        origin_x, origin_y = self._grid_origin
        return QRectF(
            target.left()
            + (8 * bounds.x + origin_x - self._source_rect.left()) * scale_x,
            target.top()
            + (8 * bounds.y + origin_y - self._source_rect.top()) * scale_y,
            8 * bounds.width * scale_x,
            8 * bounds.height * scale_y,
        )

    def _draw_forecast(self, painter: QPainter, snapshot: TrackerSnapshot) -> None:
        forecast = snapshot.forecast
        if forecast is None:
            return
        recommendation = forecast.recommendation
        probability_labels: list[QRectF] = []
        for chance in forecast.likely_routes:
            route_rect = self._route_rect(chance.location)
            if route_rect is None:
                continue
            recommended = (
                recommendation is not None
                and recommendation.route.number == chance.location.number
            )
            fill = QColor(241, 200, 75, 72 if recommended else 40)
            painter.setBrush(fill)
            painter.setPen(
                QPen(
                    GOLD,
                    3 if recommended else 2,
                    Qt.PenStyle.SolidLine if recommended else Qt.PenStyle.DashLine,
                )
            )
            painter.drawRoundedRect(route_rect, 3, 3)
            probability_labels.append(
                self._draw_probability(
                    painter,
                    route_rect.center(),
                    chance.probability,
                    probability_labels,
                )
            )

    def _draw_probability(
        self,
        painter: QPainter,
        center: QPointF,
        probability: float,
        occupied: list[QRectF],
    ) -> QRectF:
        base_rect = QRectF(center.x() - 20, center.y() - 7, 40, 14)
        label_rect = base_rect
        for offset_x, offset_y in (
            (0, 0),
            (0, -16),
            (0, 16),
            (-22, 0),
            (22, 0),
        ):
            candidate = base_rect.translated(offset_x, offset_y)
            if not any(candidate.intersects(other) for other in occupied):
                label_rect = candidate
                break
        painter.setPen(QPen(GOLD, 1))
        painter.setBrush(QColor(16, 27, 45, 225))
        painter.drawRoundedRect(label_rect, 4, 4)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(8)
        painter.setFont(font)
        painter.setPen(WHITE)
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignCenter,
            _format_probability(probability),
        )
        return label_rect

    def _draw_marker(
        self,
        painter: QPainter,
        point: tuple[float, float],
        color: QColor,
        label: str,
        *,
        diamond: bool = False,
    ) -> None:
        x, y = self._scaled(point)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(WHITE, 2))
        painter.setBrush(color)
        if diamond:
            polygon = [
                QPoint(round(x), round(y - 10)),
                QPoint(round(x + 10), round(y)),
                QPoint(round(x), round(y + 10)),
                QPoint(round(x - 10), round(y)),
            ]
            painter.drawPolygon(polygon)
        else:
            painter.drawEllipse(QRectF(x - 9, y - 9, 18, 18))
        painter.setPen(WHITE)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(
            QRectF(x - 9, y - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, label
        )

    def _draw_match(
        self,
        painter: QPainter,
        point: tuple[float, float],
        roamer_marker: str,
        player_marker: str,
    ) -> None:
        x, y = self._scaled(point)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(241, 200, 75, 70))
        painter.setPen(QPen(GOLD, 3))
        painter.drawEllipse(QRectF(x - 18, y - 18, 36, 36))
        self._draw_marker(painter, (point[0] - 2.5, point[1]), CYAN, player_marker)
        self._draw_marker(
            painter,
            (point[0] + 2.5, point[1]),
            CORAL,
            roamer_marker,
            diamond=True,
        )


class TownMapWidget(RegionMapWidget):
    """The region map on the blue field the game's town map screen uses."""

    BACKDROP = QColor("#184878")
    FRAME = QColor("#101828")


class TownMapView(DragBar):
    """Compact layout inspired by the GBA town-map screens.

    The map fills the window and the tracker speaks through the game's
    message box, one page at a time, instead of through standing panels.
    """

    SIZE = (448, 472)
    PLATE = QRectF(16, 16, 416, 56)
    BOX = QRectF(16, 388, 416, 68)
    BUTTON_SPACING = 6
    PAGE_MS = 2600
    CARET_MS = 450

    INK_TEXT = QColor("#282830")
    BLUE_TEXT = QColor("#4870b0")
    TEXT_SHADOW = QColor("#b8b8c8")
    BLUE_SHADOW = QColor("#c8d8f0")

    def __init__(self, window: TrackerWindow) -> None:
        super().__init__(window)
        self.setFixedSize(*self.SIZE)
        self.setAccessibleName("Rastreador de roamers sobre el mapa regional")
        self._snapshot: TrackerSnapshot | None = None
        self._live = False
        self._page = 0
        self._caret = True

        self.map = TownMapWidget(self, size=(416, 288))
        self.map.move(16, 84)

        self.pin_button = QToolButton(self)
        self.pin_button.setObjectName("pinButton")
        self.pin_button.setIcon(_pin_icon())
        self.pin_button.setIconSize(QSize(13, 13))
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(window.pinned)
        self.pin_button.setToolTip("Mantener siempre visible")
        self.pin_button.toggled.connect(window.set_always_on_top)

        self.settings_button = _settings_button(window, self)

        self.close_button = QToolButton(self)
        self.close_button.setObjectName("closeButton")
        self.close_button.setText("×")
        self.close_button.setToolTip("Cerrar")
        self.close_button.clicked.connect(window.close)

        self.setStyleSheet(
            """
            QToolButton {
                min-width: 22px;
                min-height: 22px;
                border: 2px solid #4870b0;
                border-radius: 4px;
                background: #f8f8f8;
                color: #404048;
                font-size: 11px;
                font-weight: 700;
            }
            QToolButton:hover { background: #d8e4f8; }
            QToolButton:checked { background: #a8c0e0; }
            QMenu {
                background: #f8f8f8;
                border: 2px solid #4870b0;
                color: #404048;
                font-size: 11px;
            }
            QMenu::item { padding: 5px 18px; }
            QMenu::item:selected { background: #d8e4f8; }
            QMenu::item:disabled { color: #8890a0; font-size: 9px; }
            """
        )
        self._place_buttons()

        self._page_timer = QTimer(self)
        self._page_timer.timeout.connect(self._turn_page)
        self._page_timer.start(self.PAGE_MS)
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._blink_caret)
        self._caret_timer.start(self.CARET_MS)

    def _place_buttons(self) -> None:
        """Centre the buttons in the plate and record where the status ends."""
        right = int(self.PLATE.right()) - 12
        middle = int(self.PLATE.center().y())
        for button in (self.close_button, self.pin_button, self.settings_button):
            size = button.sizeHint()
            right -= size.width()
            button.move(right, middle - size.height() // 2)
            right -= self.BUTTON_SPACING
        self._status_right = right

    def set_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self._snapshot = snapshot
        self.map.set_snapshot(snapshot)
        self.update()

    def set_connection(self, live: bool) -> None:
        self._live = live
        self.update()

    def _turn_page(self) -> None:
        self._page += 1
        self.update()

    def _blink_caret(self) -> None:
        self._caret = not self._caret
        self.update()

    def pages(self) -> list[str]:
        """The message-box script for the current situation, in order."""
        snapshot = self._snapshot
        if snapshot is None:
            return ["Buscando el juego…"]
        species = snapshot.roamer.species.name.upper()
        if not snapshot.roamer.active:
            region = snapshot.game.region_map.name.upper()
            return [
                f"{species} todavía no recorre {region}.",
                "El rastreador sigue mirando.",
            ]
        if snapshot.same_area:
            return [
                f"¡{species} está en tu misma zona!",
                f"Buscá en {snapshot.player.name.upper()}.",
            ]
        player = snapshot.player.name.upper()
        script = [
            f"{species} está en {snapshot.roamer.location.name.upper()}.\n"
            + (
                f"{snapshot.player_name.upper()} está en {player}."
                if snapshot.player_name
                else f"Vos estás en {player}."
            )
        ]
        forecast = snapshot.forecast
        if forecast is None:
            return script
        script.append(
            "Próximo movimiento:\n"
            + "   ".join(
                f"{chance.location.name.upper()} "
                f"{_format_probability(chance.probability)}"
                for chance in forecast.likely_routes[:3]
            )
        )
        recommendation = forecast.recommendation
        if recommendation is not None:
            script.append(
                f"¡Cruzá a {recommendation.route.name.upper()} ahora!\n"
                "Lo interceptás en el próximo cambio."
            )
        return script

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        field = QLinearGradient(0, 0, 0, self.height())
        field.setColorAt(0.0, QColor("#3878c8"))
        field.setColorAt(0.5, QColor("#204878"))
        field.setColorAt(1.0, QColor("#102038"))
        painter.setBrush(field)
        painter.setPen(QPen(QColor("#0c1828"), 2))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)

        self._paint_plate(painter)
        self._paint_message(painter)

    def _paint_plate(self, painter: QPainter) -> None:
        _message_box(painter, self.PLATE)
        snapshot = self._snapshot
        if snapshot is None:
            title, subtitle = "RASTREADOR", "MAPA REGIONAL"
        else:
            title = snapshot.roamer.species.name.upper()
            subtitle = (
                snapshot.roamer.location.name.upper()
                if snapshot.roamer.active
                else snapshot.game.region_map.name.upper()
            )
            painter.drawPixmap(
                26,
                20,
                _scaled_sprite(str(ROAMER_ASSETS[snapshot.roamer.species]), 48),
            )

        painter.setFont(_pixel_font(15, bold=True))
        _gba_text(
            painter,
            QRectF(84, 22, 240, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
            self.INK_TEXT,
            self.TEXT_SHADOW,
        )
        painter.setFont(_pixel_font(10, bold=True))
        _gba_text(
            painter,
            QRectF(84, 46, 190, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            subtitle,
            self.BLUE_TEXT,
            self.BLUE_SHADOW,
        )
        # Same row as the buttons, ending where _place_buttons() left off.
        middle = self.PLATE.center().y()
        _gba_text(
            painter,
            QRectF(200, middle - 9, self._status_right - 212, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"● {'EN VIVO' if self._live else 'SIN CONEXIÓN'}",
            LIVE if self._live else CORAL,
            QColor("#e0e4ec"),
        )

    def current_page(self) -> str:
        script = self.pages()
        return script[self._page % len(script)]

    def _paint_message(self, painter: QPainter) -> None:
        _message_box(painter, self.BOX)
        script = self.pages()
        painter.setFont(_pixel_font(13))
        _gba_text(
            painter,
            self.BOX.adjusted(18, 12, -26, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            self.current_page(),
            self.INK_TEXT,
            self.TEXT_SHADOW,
        )
        if not self._caret or len(script) < 2:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.BLUE_TEXT)
        corner = self.BOX.bottomRight()
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(corner.x() - 30, corner.y() - 22),
                    QPointF(corner.x() - 16, corner.y() - 22),
                    QPointF(corner.x() - 23, corner.y() - 13),
                ]
            )
        )


class TrackerWindow(QWidget):
    def __init__(
        self,
        host: str,
        port: int,
        interval: float,
        *,
        ui: str = CLASSIC_UI,
        start_worker: bool = True,
        pin_controller: PinController | None | _AutoPinController = AUTO_PIN_CONTROLLER,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        if ui not in UI_LAYOUTS:
            raise ValueError("diseño de interfaz desconocido")
        self.host = host
        self.port = port
        self.ui = ui
        self.pinned = True
        self._settings = settings if settings is not None else tracker_settings()
        self._snapshot: TrackerSnapshot | None = None
        self._live = False
        if isinstance(pin_controller, _AutoPinController):
            resolved_pin_controller: PinController | None = (
                KWinPinController.for_current_session()
            )
        else:
            resolved_pin_controller = pin_controller
        self._pin_controller = resolved_pin_controller
        self._initial_pin_pending = self._pin_controller is not None
        self._displayed_species: RoamerSpecies | None = None
        self._displayed_game: Game | None = None
        self.setObjectName("shell")
        self.setWindowTitle("Rastreador de roamers")
        self.setWindowIcon(QIcon(str(ASSET_ROOT / "app_icon.png")))
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self._pin_controller is None:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # ponytail: two layouts, so the classic one stays inlined here and the
        # town map is a child view. Extract a ClassicView if a third arrives.
        self.town_map: TownMapView | None = None
        self._build_layout()

        self.worker = TrackerThread(host, port, interval, self)
        self.worker.snapshot_ready.connect(self.show_snapshot)
        self.worker.connection_changed.connect(self.show_connection)
        if start_worker:
            self.worker.start()

    def set_ui_layout(self, ui: str) -> None:
        """Switch layouts and remember the choice for the next launch."""
        if ui not in UI_LAYOUTS:
            raise ValueError("diseño de interfaz desconocido")
        if ui == self.ui:
            return
        self.ui = ui
        self._settings.setValue(UI_SETTINGS_KEY, ui)
        # The menu item that asked for this belongs to the widgets about to be
        # destroyed, so rebuild once Qt is done delivering its signal.
        QTimer.singleShot(0, self._rebuild_layout)

    def _rebuild_layout(self) -> None:
        self._build_layout()
        self._displayed_species = None
        self._displayed_game = None
        self.show_connection(self._live)
        if self._snapshot is not None:
            self.show_snapshot(self._snapshot)

    def _build_layout(self) -> None:
        previous = self.layout()
        if previous is not None:
            # A widget only ever accepts one layout, so hand the old one and
            # the widgets it holds to a throwaway parent that takes them down.
            QWidget().setLayout(previous)
        self.town_map = None
        if self.ui == TOWN_MAP_UI:
            self._build_town_map_ui()
        else:
            self.setFixedSize(512, 680)
            self._build_ui()
            self._apply_styles()

    def _build_town_map_ui(self) -> None:
        self.setStyleSheet("QWidget#shell { background: transparent; }")
        self.setFixedSize(*TownMapView.SIZE)
        self.town_map = TownMapView(self)
        self.pin_button = self.town_map.pin_button
        self.settings_button = self.town_map.settings_button
        self.map = self.town_map.map
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.town_map)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = DragBar()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(46)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 8, 0)
        title_layout.setSpacing(7)

        mark = QLabel("R")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(25, 25)
        self.brand = QLabel("RASTREADOR  /  MAPA REGIONAL")
        self.brand.setObjectName("brand")
        title_layout.addWidget(mark)
        title_layout.addWidget(self.brand)
        title_layout.addStretch()

        self.settings_button = _settings_button(self)
        title_layout.addWidget(self.settings_button)

        self.pin_button = QToolButton()
        self.pin_button.setObjectName("pinButton")
        self.pin_button.setIcon(_pin_icon())
        self.pin_button.setIconSize(QSize(15, 15))
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self.pinned)
        self.pin_button.setToolTip("Mantener siempre visible")
        self.pin_button.toggled.connect(self.set_always_on_top)
        title_layout.addWidget(self.pin_button)

        minimize = QToolButton()
        minimize.setText("—")
        minimize.setToolTip("Minimizar")
        minimize.clicked.connect(self.showMinimized)
        title_layout.addWidget(minimize)

        close = QToolButton()
        close.setObjectName("closeButton")
        close.setText("×")
        close.setToolTip("Cerrar")
        close.clicked.connect(self.close)
        title_layout.addWidget(close)
        root.addWidget(title_bar)

        content = QFrame()
        content.setObjectName("content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 15)
        layout.setSpacing(10)

        connection_row = QHBoxLayout()
        connection_row.setSpacing(7)
        self.connection_dot = InlineIcon("dot", GOLD, 14)
        self.connection_dot.setObjectName("connectionDot")
        self.connection_label = QLabel("BUSCANDO EL JUEGO…")
        self.connection_label.setObjectName("connectionLabel")
        endpoint = QLabel(f"{self.host}:{self.port}")
        endpoint.setObjectName("endpoint")
        connection_row.addWidget(
            self.connection_dot,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        connection_row.addWidget(
            self.connection_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        connection_row.addStretch()
        connection_row.addWidget(endpoint, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(connection_row)

        self.map = RegionMapWidget()
        layout.addWidget(self.map, 0, Qt.AlignmentFlag.AlignCenter)

        legend = QHBoxLayout()
        legend.setSpacing(14)
        self.player_legend_label = QLabel(PLAYER_FALLBACK_NAME)
        legend.addWidget(
            self._legend(
                "dot",
                PLAYER_FALLBACK_NAME,
                "player",
                CYAN,
                label=self.player_legend_label,
            )
        )
        self.roamer_legend_label = QLabel("ROAMER")
        legend.addWidget(
            self._legend(
                "diamond",
                "ROAMER",
                "roamer",
                CORAL,
                label=self.roamer_legend_label,
            )
        )
        legend.addWidget(self._legend("route", "PRÓX.", "next", GOLD))
        legend.addStretch()
        layout.addLayout(legend)

        self.match_banner = QFrame()
        self.match_banner.setObjectName("matchBanner")
        self.match_banner.setProperty("matched", False)
        self.match_banner.setProperty("mode", "idle")
        match_layout = QHBoxLayout(self.match_banner)
        match_layout.setContentsMargins(12, 8, 12, 8)
        match_layout.setSpacing(8)
        self.match_icon = InlineIcon("ring", MUTED, 19)
        self.match_icon.setObjectName("matchIcon")
        self.match_text = QLabel("Calculando próximo movimiento")
        self.match_text.setObjectName("matchText")
        self.match_hint = QLabel("")
        self.match_hint.setObjectName("matchHint")
        match_layout.addWidget(
            self.match_icon,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        match_layout.addWidget(
            self.match_text,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        match_layout.addStretch()
        match_layout.addWidget(
            self.match_hint,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        layout.addWidget(self.match_banner)

        locations = QHBoxLayout()
        locations.setSpacing(10)
        self.roamer_location = QLabel("—")
        self.player_location = QLabel("—")
        self.roamer_heading = QLabel("ROAMER")
        self.player_heading = QLabel(PLAYER_FALLBACK_NAME)
        self.roamer_sprite = QLabel()
        locations.addWidget(
            self._location_card(
                "ROAMER",
                self.roamer_location,
                "roamerCard",
                heading=self.roamer_heading,
                sprite=self.roamer_sprite,
            ),
            3,
        )
        locations.addWidget(
            self._location_card(
                PLAYER_FALLBACK_NAME,
                self.player_location,
                "playerCard",
                heading=self.player_heading,
            ),
            2,
        )
        layout.addLayout(locations)
        layout.addWidget(self._stats_card())
        root.addWidget(content)

    def _stats_card(self) -> QFrame:
        """The roamer's battle identity, so a hunter can judge it before the
        encounter starts."""
        card = QFrame()
        card.setObjectName("statsCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(11, 8, 11, 8)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(4)
        heading = QLabel("DATOS DEL ROAMER")
        heading.setObjectName("cardHeading")
        grid.addWidget(heading, 0, 0, 1, 4)

        self.stat_values: dict[str, QLabel] = {}
        for key, title, row, column in STAT_FIELDS:
            grid.addWidget(self._stat_name(title), row, column)
            grid.addWidget(self._stat_value(key), row, column + 1)
        grid.addWidget(self._stat_name("IVS"), 3, 0)
        grid.addWidget(self._stat_value("ivs"), 3, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    @staticmethod
    def _stat_name(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("statName")
        return label

    def _stat_value(self, key: str) -> QLabel:
        label = QLabel(MISSING_STAT)
        label.setObjectName("statValue")
        self.stat_values[key] = label
        return label

    def _legend(
        self,
        kind: str,
        text: str,
        tone: str,
        color: QColor,
        *,
        label: QLabel | None = None,
    ) -> QWidget:
        item = QWidget()
        row = QHBoxLayout(item)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        icon = InlineIcon(kind, color, 13)
        icon.setObjectName(f"{tone}Legend")
        label = label or QLabel(text)
        label.setObjectName("legendLabel")
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        return item

    def _location_card(
        self,
        title: str,
        value: QLabel,
        object_name: str,
        sprite_path: Path | None = None,
        *,
        heading: QLabel | None = None,
        sprite: QLabel | None = None,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(object_name)
        row = QHBoxLayout(card)
        row.setContentsMargins(11, 8, 11, 8)
        row.setSpacing(9)
        if sprite_path is not None or sprite is not None:
            sprite = sprite or QLabel()
            sprite.setObjectName("roamerSprite")
            if sprite_path is not None:
                pixmap = QPixmap(str(sprite_path)).scaled(
                    58,
                    58,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                sprite.setPixmap(pixmap)
            sprite.setFixedSize(58, 58)
            row.addWidget(sprite)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        heading = heading or QLabel(title)
        heading.setObjectName("cardHeading")
        value.setObjectName("locationValue")
        value.setWordWrap(True)
        labels.addWidget(heading)
        labels.addWidget(value)
        labels.addStretch()
        row.addLayout(labels, 1)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        card.setFixedHeight(78)
        return card

    def _apply_styles(self) -> None:
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.setStyleSheet(
            f"""
            QWidget#shell {{
                background: transparent;
                color: #f9f5e7;
                font-family: "{fixed}";
                font-size: 12px;
            }}
            QFrame#titleBar {{
                background: #172640;
                border: 1px solid #304260;
                border-bottom: 0;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
            QFrame#content {{
                background: #101b2d;
                border: 1px solid #304260;
                border-top: 0;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
            QLabel#brandMark {{
                color: #fff9e8;
                background: #e2554d;
                border: 2px solid #fff9e8;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 800;
            }}
            QLabel#brand {{
                color: #fff9e8;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QToolButton {{
                min-width: 25px;
                min-height: 25px;
                border: 0;
                border-radius: 5px;
                color: #9aabc1;
                background: transparent;
                font-size: 15px;
            }}
            QToolButton:hover {{ background: #263a5b; color: #fff9e8; }}
            QToolButton#closeButton:hover {{ background: #e2554d; }}
            QToolButton#pinButton {{
                border: 1px solid #3a5478;
            }}
            QToolButton#pinButton:checked {{
                color: #172640;
                background: #f1c84b;
                border-color: #f1c84b;
            }}
            QMenu {{
                background: #172640;
                border: 1px solid #304260;
                color: #dce5ec;
                font-size: 11px;
            }}
            QMenu::item {{ padding: 5px 18px; }}
            QMenu::item:selected {{ background: #263a5b; color: #fff9e8; }}
            QMenu::item:disabled {{
                color: #7387a1;
                font-size: 9px;
                font-weight: 700;
            }}
            QLabel#connectionLabel {{
                color: #dce5ec;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#endpoint {{ color: #7387a1; font-size: 9px; }}
            QLabel#legendLabel {{ color: #9aabc1; font-size: 9px; font-weight: 700; }}
            QFrame#matchBanner {{
                background: #172640;
                border: 1px solid #304260;
                border-radius: 7px;
            }}
            QFrame#matchBanner[matched="true"] {{
                background: #443917;
                border-color: #f1c84b;
            }}
            QFrame#matchBanner[mode="cross"] {{
                background: #302d1d;
                border-color: #f1c84b;
            }}
            QLabel#matchText {{ color: #dce5ec; font-size: 11px; font-weight: 700; }}
            QFrame#matchBanner[matched="true"] QLabel#matchText {{ color: #fff4b0; }}
            QLabel#matchHint {{ color: #7387a1; font-size: 9px; }}
            QFrame#matchBanner[mode="cross"] QLabel#matchHint {{ color: #d7bd63; }}
            QFrame#roamerCard, QFrame#playerCard {{
                background: #172640;
                border: 1px solid #304260;
                border-radius: 8px;
            }}
            QFrame#roamerCard {{ border-left: 3px solid #e2554d; }}
            QFrame#playerCard {{ border-left: 3px solid #49b8d0; }}
            QFrame#statsCard {{
                background: #172640;
                border: 1px solid #304260;
                border-left: 3px solid #f1c84b;
                border-radius: 8px;
            }}
            QLabel#statName {{
                color: #8296af;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#statValue {{ color: #fff9e8; font-size: 11px; font-weight: 700; }}
            QLabel#cardHeading {{
                color: #8296af;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#locationValue {{ color: #fff9e8; font-size: 14px; font-weight: 700; }}
            """
        )

    def show_connection(self, live: bool) -> None:
        self._live = live
        if self.town_map is not None:
            self.town_map.set_connection(live)
            return
        self.connection_dot.set_icon("dot", LIVE if live else CORAL)
        self.connection_label.setText(
            "EN VIVO" if live else "SIN CONEXIÓN · REINTENTANDO"
        )

    def show_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self._snapshot = snapshot
        self._show_game(snapshot.game)
        self._show_species(snapshot.roamer.species)
        if self.town_map is not None:
            self.town_map.set_snapshot(snapshot)
            return
        self.map.set_snapshot(snapshot)
        self._show_stats(snapshot.roamer.stats)
        self.roamer_location.setText(
            snapshot.roamer.location.name if snapshot.roamer.active else "INACTIVO"
        )
        self.player_location.setText(snapshot.player.name)
        trainer = player_name(snapshot).upper()
        self.player_heading.setText(trainer)
        self.player_legend_label.setText(trainer)
        mode = "idle"
        tooltip = ""
        if not snapshot.roamer.active:
            self.match_icon.set_icon("dash", MUTED)
            self.match_text.setText("El roamer no está activo")
            self.match_hint.setText(
                f"Todavía no recorre {snapshot.game.region_map.name}"
            )
        elif snapshot.same_area:
            mode = "matched"
            self.match_icon.set_icon("double-ring", GOLD)
            self.match_text.setText("¡MISMA ZONA!")
            self.match_hint.setText("")
        elif snapshot.forecast is not None:
            recommendation = snapshot.forecast.recommendation
            tooltip = "Próximo movimiento: " + ", ".join(
                f"{chance.location.name} {_format_probability(chance.probability)}"
                for chance in snapshot.forecast.likely_routes
            )
            if recommendation is not None:
                mode = "cross"
                self.match_icon.set_icon("arrow", GOLD)
                self.match_text.setText(
                    f"CRUZÁ A {recommendation.route.name.upper()}"
                    f" · {_format_probability(recommendation.probability)}"
                )
                self.match_hint.setText("INTERCEPCIÓN EN EL PRÓXIMO CAMBIO")
            else:
                self.match_icon.set_icon("ring", MUTED)
                self.match_text.setText("PRÓXIMO MOVIMIENTO")
                self.match_hint.setText("RUTAS PROBABLES EN EL MAPA")
        else:
            self.match_icon.set_icon("ring", MUTED)
            self.match_text.setText("Movimiento no disponible")
            self.match_hint.setText("")

        self.match_banner.setToolTip(tooltip)
        self.match_banner.setProperty("matched", snapshot.same_area)
        self.match_banner.setProperty("mode", mode)
        self.match_banner.style().unpolish(self.match_banner)
        self.match_banner.style().polish(self.match_banner)

    def _show_stats(self, stats: RoamerStats | None) -> None:
        """Fill the classic layout's roamer readouts, or blank them out."""
        if stats is None:
            for label in self.stat_values.values():
                label.setText(MISSING_STAT)
            return
        self.stat_values["pid"].setText(f"{stats.personality:08X}")
        self.stat_values["nature"].setText(stats.nature)
        self.stat_values["hp"].setText(f"{stats.hp} / {stats.max_hp}")
        self.stat_values["status"].setText(stats.status or "Sin estado")
        self.stat_values["ivs"].setText(stats.iv_summary)

    def _show_game(self, game: Game) -> None:
        if game == self._displayed_game:
            return
        self._displayed_game = game
        if self.town_map is None:
            self.brand.setText(f"RASTREADOR  /  {game.region_map.name.upper()}")

    def _show_species(self, species: RoamerSpecies) -> None:
        if species == self._displayed_species:
            return
        self._displayed_species = species
        sprite_path = ROAMER_ASSETS[species]
        self.setWindowTitle(f"Rastreador de {species.name}")
        self.setWindowIcon(QIcon(str(sprite_path)))
        if self.town_map is not None:
            # The town map paints the sprite and the name inside its plate.
            return
        name = species.name.upper()
        self.roamer_sprite.setPixmap(_scaled_sprite(str(sprite_path), 58))
        self.roamer_heading.setText(name)
        self.roamer_legend_label.setText(name)

    def set_always_on_top(self, enabled: bool) -> None:
        self.pinned = enabled
        if self._pin_controller is not None:
            if self._initial_pin_pending:
                # A click before the first activation changes the requested
                # state from the default (unpinned in KWin). Do not toggle the
                # previously active application by accident.
                self._initial_pin_pending = False
                if not enabled:
                    return
            if self._pin_controller.toggle():
                return
            # If the desktop integration disappears, keep the portable Qt
            # behavior available instead of leaving a dead control.
            self._pin_controller = None
        self._set_qt_always_on_top(enabled)

    def _set_qt_always_on_top(self, enabled: bool) -> None:
        position = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        # Qt hides a top-level widget when a window flag changes.
        self.show()
        self.move(position)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._initial_pin_pending:
            return
        app = QApplication.instance()
        if isinstance(app, QApplication) and app.platformName() != "offscreen":
            self.activateWindow()
        QTimer.singleShot(50, self._apply_initial_pin)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ActivationChange
            and self._initial_pin_pending
            and self.isActiveWindow()
        ):
            QTimer.singleShot(0, self._apply_initial_pin)

    def _apply_initial_pin(self) -> None:
        if (
            self._pin_controller is None
            or not self._initial_pin_pending
            or not self.isActiveWindow()
        ):
            return
        self._initial_pin_pending = False
        if not self._pin_controller.toggle():
            self._pin_controller = None
            self._set_qt_always_on_top(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_tracking()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def stop_tracking(self) -> None:
        """Stop the polling thread once, regardless of the shutdown source."""
        if not self.worker.isRunning():
            return
        self.worker.stop()
        self.worker.wait()


def positive_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("el puerto debe estar entre 1 y 65535")
    return port


def positive_interval(value: str) -> float:
    interval = float(value)
    if interval <= 0:
        raise argparse.ArgumentTypeError("el intervalo debe ser mayor que cero")
    return interval


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ventana flotante para rastrear roamers de Pokémon en GBA."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive_port, default=55355)
    parser.add_argument("--interval", type=positive_interval, default=0.20)
    parser.add_argument(
        "--ui",
        choices=UI_LAYOUTS,
        default=None,
        help="diseño de la ventana; se recuerda para las próximas veces",
    )
    args = parser.parse_args()

    app = QApplication([])
    app.setApplicationName("Rastreador de roamers")
    app.setQuitOnLastWindowClosed(True)

    settings = tracker_settings()
    if args.ui is None:
        ui = stored_ui_layout(settings)
    else:
        ui = args.ui
        settings.setValue(UI_SETTINGS_KEY, ui)
    window = TrackerWindow(
        args.host, args.port, args.interval, ui=ui, settings=settings
    )
    app.aboutToQuit.connect(window.stop_tracking)

    # Python's default SIGINT handler raises KeyboardInterrupt wherever the
    # interpreter next runs Python code, which can be inside a Qt slot. Convert
    # it into an orderly window close instead. The timer gives Python regular
    # opportunities to dispatch a pending signal while Qt owns the event loop.
    interrupt_timer = QTimer()
    interrupt_timer.setInterval(200)
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start()

    def request_shutdown() -> None:
        window.close()

    def handle_interrupt(_signum, _frame) -> None:
        QTimer.singleShot(0, request_shutdown)

    previous_interrupt_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_interrupt)
    window.show()
    try:
        return app.exec()
    finally:
        signal.signal(signal.SIGINT, previous_interrupt_handler)


if __name__ == "__main__":
    raise SystemExit(main())
