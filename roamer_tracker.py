"""Always-on-top desktop GUI for the FireRed roaming Pokémon tracker."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
from threading import Event
from typing import Protocol

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if __package__:
    from .tracker import (
        ENTEI,
        Location,
        RAIKOU,
        RoamerSpecies,
        SUICUNE,
        RetroArchNCI,
        TrackerError,
        TrackerSnapshot,
        read_snapshot,
    )
else:
    from tracker import (
        ENTEI,
        Location,
        RAIKOU,
        RoamerSpecies,
        SUICUNE,
        RetroArchNCI,
        TrackerError,
        TrackerSnapshot,
        read_snapshot,
    )


APP_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = APP_ROOT / "assets"
ROAMER_ASSETS = {
    RAIKOU: ASSET_ROOT / "raikou.png",
    ENTEI: ASSET_ROOT / "entei.png",
    SUICUNE: ASSET_ROOT / "suicune.png",
}

NAVY = QColor("#172640")
INK = QColor("#101b2d")
CYAN = QColor("#49b8d0")
CORAL = QColor("#e2554d")
GOLD = QColor("#f1c84b")
WHITE = QColor("#fff9e8")


def _format_probability(probability: float) -> str:
    return f"{probability:.1%}".replace(".", ",")


class PinController(Protocol):
    def toggle(self) -> bool: ...


class KWinPinController:
    """Toggle KWin's real keep-above state on the active Wayland window."""

    SHORTCUT = "Window Above Other Windows"

    def __init__(self, interface: QDBusInterface) -> None:
        self.interface = interface

    @classmethod
    def for_current_session(cls) -> KWinPinController | None:
        app = QApplication.instance()
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
        if app is None or app.platformName() != "wayland" or "kde" not in desktop:
            return None
        interface = QDBusInterface(
            "org.kde.kglobalaccel",
            "/component/kwin",
            "org.kde.kglobalaccel.Component",
            QDBusConnection.sessionBus(),
        )
        if not interface.isValid():
            return None
        return cls(interface)

    def toggle(self) -> bool:
        shortcuts_reply = self.interface.call("shortcutNames")
        if shortcuts_reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return False
        arguments = shortcuts_reply.arguments()
        if (
            len(arguments) != 1
            or not isinstance(arguments[0], list)
            or self.SHORTCUT not in arguments[0]
        ):
            return False
        reply = self.interface.call("invokeShortcut", self.SHORTCUT)
        return reply.type() == QDBusMessage.MessageType.ReplyMessage


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
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        self._system_move_active = False
        super().mouseReleaseEvent(event)


class KantoMap(QWidget):
    """Paint the original 240x160 map at exact 2x scale with live markers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("kantoMap")
        self.setFixedSize(480, 320)
        self.setAccessibleName("Mapa de Kanto con la ubicación del roamer y del jugador")
        self._map = QPixmap(str(ASSET_ROOT / "kanto_map.png"))
        self._snapshot: TrackerSnapshot | None = None

    def set_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self._snapshot = snapshot
        self.update()

    @staticmethod
    def _point(location: Location) -> tuple[float, float] | None:
        if location.map_bounds is None:
            return None
        grid_x, grid_y = location.map_bounds.center
        # These offsets are the cursor formula from pret/pokefirered's
        # src/region_map.c: x = 8 * grid_x + 36, y = 8 * grid_y + 36.
        return (8 * grid_x + 36, 8 * grid_y + 36)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.fillRect(self.rect(), INK)
        painter.drawPixmap(
            QRectF(self.rect()),
            self._map,
            QRectF(self._map.rect()),
        )

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
            if self._snapshot.same_area and player is not None:
                self._draw_match(painter, player, marker)
            else:
                if self._snapshot.roamer.active and roamer is not None:
                    self._draw_marker(painter, roamer, CORAL, marker, diamond=True)
                if player is not None:
                    self._draw_marker(painter, player, CYAN, "V")

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#304260"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def _scaled(self, point: tuple[float, float]) -> tuple[float, float]:
        return point[0] * self.width() / 240, point[1] * self.height() / 160

    def _route_rect(self, location: Location) -> QRectF | None:
        bounds = location.map_bounds
        if bounds is None:
            return None
        scale_x = self.width() / 240
        scale_y = self.height() / 160
        return QRectF(
            (8 * bounds.x + 32) * scale_x,
            (8 * bounds.y + 32) * scale_y,
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
        painter.drawText(QRectF(x - 9, y - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, label)

    def _draw_match(
        self,
        painter: QPainter,
        point: tuple[float, float],
        roamer_marker: str,
    ) -> None:
        x, y = self._scaled(point)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(241, 200, 75, 70))
        painter.setPen(QPen(GOLD, 3))
        painter.drawEllipse(QRectF(x - 18, y - 18, 36, 36))
        self._draw_marker(painter, (point[0] - 2.5, point[1]), CYAN, "V")
        self._draw_marker(
            painter,
            (point[0] + 2.5, point[1]),
            CORAL,
            roamer_marker,
            diamond=True,
        )


class TrackerWindow(QWidget):
    def __init__(
        self,
        host: str,
        port: int,
        interval: float,
        *,
        start_worker: bool = True,
        pin_controller: PinController | None | _AutoPinController = AUTO_PIN_CONTROLLER,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        if pin_controller is AUTO_PIN_CONTROLLER:
            self._pin_controller: PinController | None = (
                KWinPinController.for_current_session()
            )
        else:
            self._pin_controller = pin_controller
        self._initial_pin_pending = self._pin_controller is not None
        self._displayed_species: RoamerSpecies | None = None
        self.setObjectName("shell")
        self.setWindowTitle("Rastreador de roamers")
        self.setWindowIcon(QIcon(str(ASSET_ROOT / "app_icon.png")))
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self._pin_controller is None:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(512, 680)
        self._build_ui()
        self._apply_styles()

        self.worker = TrackerThread(host, port, interval, self)
        self.worker.snapshot_ready.connect(self.show_snapshot)
        self.worker.connection_changed.connect(self.show_connection)
        if start_worker:
            self.worker.start()

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
        brand = QLabel("RASTREADOR  /  KANTO")
        brand.setObjectName("brand")
        title_layout.addWidget(mark)
        title_layout.addWidget(brand)
        title_layout.addStretch()

        self.pin_button = QToolButton()
        self.pin_button.setObjectName("pinButton")
        self.pin_button.setText("FIJO")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
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
        self.connection_dot = QLabel("●")
        self.connection_dot.setObjectName("connectionDot")
        self.connection_label = QLabel("BUSCANDO EL JUEGO…")
        self.connection_label.setObjectName("connectionLabel")
        endpoint = QLabel(f"{self.host}:{self.port}")
        endpoint.setObjectName("endpoint")
        connection_row.addWidget(self.connection_dot)
        connection_row.addWidget(self.connection_label)
        connection_row.addStretch()
        connection_row.addWidget(endpoint)
        layout.addLayout(connection_row)

        self.map = KantoMap()
        layout.addWidget(self.map, 0, Qt.AlignmentFlag.AlignCenter)

        legend = QHBoxLayout()
        legend.setSpacing(14)
        legend.addWidget(self._legend("●", "VOS", "player"))
        self.roamer_legend_label = QLabel("ROAMER")
        legend.addWidget(
            self._legend(
                "◆",
                "ROAMER",
                "roamer",
                label=self.roamer_legend_label,
            )
        )
        legend.addWidget(self._legend("▱", "PRÓX.", "next"))
        legend.addStretch()
        layout.addLayout(legend)

        self.match_banner = QFrame()
        self.match_banner.setObjectName("matchBanner")
        self.match_banner.setProperty("matched", False)
        self.match_banner.setProperty("mode", "idle")
        match_layout = QHBoxLayout(self.match_banner)
        match_layout.setContentsMargins(12, 8, 12, 8)
        match_layout.setSpacing(8)
        self.match_icon = QLabel("○")
        self.match_icon.setObjectName("matchIcon")
        self.match_text = QLabel("Calculando próximo movimiento")
        self.match_text.setObjectName("matchText")
        self.match_hint = QLabel("")
        self.match_hint.setObjectName("matchHint")
        match_layout.addWidget(self.match_icon)
        match_layout.addWidget(self.match_text)
        match_layout.addStretch()
        match_layout.addWidget(self.match_hint)
        layout.addWidget(self.match_banner)

        locations = QHBoxLayout()
        locations.setSpacing(10)
        self.roamer_location = QLabel("—")
        self.player_location = QLabel("—")
        self.roamer_heading = QLabel("ROAMER")
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
            self._location_card("VOS", self.player_location, "playerCard"),
            2,
        )
        layout.addLayout(locations)
        root.addWidget(content)

    def _legend(
        self,
        symbol: str,
        text: str,
        tone: str,
        *,
        label: QLabel | None = None,
    ) -> QWidget:
        item = QWidget()
        row = QHBoxLayout(item)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        icon = QLabel(symbol)
        icon.setObjectName(f"{tone}Legend")
        label = label or QLabel(text)
        label.setObjectName("legendLabel")
        row.addWidget(icon)
        row.addWidget(label)
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
                min-width: 43px;
                font-size: 9px;
                font-weight: 700;
                border: 1px solid #3a5478;
            }}
            QToolButton#pinButton:checked {{
                color: #172640;
                background: #f1c84b;
                border-color: #f1c84b;
            }}
            QLabel#connectionDot {{ color: #f1c84b; font-size: 13px; }}
            QLabel#connectionDot[live="true"] {{ color: #63c79a; }}
            QLabel#connectionDot[live="false"] {{ color: #e2554d; }}
            QLabel#connectionLabel {{
                color: #dce5ec;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#endpoint {{ color: #7387a1; font-size: 9px; }}
            QLabel#playerLegend {{ color: #49b8d0; font-size: 15px; }}
            QLabel#roamerLegend {{ color: #e2554d; font-size: 15px; }}
            QLabel#nextLegend {{ color: #f1c84b; font-size: 15px; }}
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
            QLabel#matchIcon {{ color: #7387a1; font-size: 19px; }}
            QFrame#matchBanner[matched="true"] QLabel#matchIcon {{ color: #f1c84b; }}
            QFrame#matchBanner[mode="cross"] QLabel#matchIcon {{ color: #f1c84b; }}
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
        self.connection_dot.setProperty("live", live)
        self.connection_dot.style().unpolish(self.connection_dot)
        self.connection_dot.style().polish(self.connection_dot)
        self.connection_label.setText("EN VIVO" if live else "SIN CONEXIÓN · REINTENTANDO")

    def show_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self._show_species(snapshot.roamer.species)
        self.map.set_snapshot(snapshot)
        self.roamer_location.setText(
            snapshot.roamer.location.name if snapshot.roamer.active else "INACTIVO"
        )
        self.player_location.setText(snapshot.player.name)
        mode = "idle"
        tooltip = ""
        if not snapshot.roamer.active:
            self.match_icon.setText("—")
            self.match_text.setText("El roamer no está activo")
            self.match_hint.setText("Todavía no recorre Kanto")
        elif snapshot.same_area:
            mode = "matched"
            self.match_icon.setText("◎")
            self.match_text.setText("¡MISMA ZONA!")
            self.match_hint.setText("")
        elif snapshot.forecast is not None:
            recommendation = snapshot.forecast.recommendation
            tooltip = "Próximo movimiento: " + ", ".join(
                f"{chance.location.name} "
                f"{_format_probability(chance.probability)}"
                for chance in snapshot.forecast.likely_routes
            )
            if recommendation is not None:
                mode = "cross"
                self.match_icon.setText("↗")
                self.match_text.setText(
                    f"CRUZÁ A {recommendation.route.name.upper()}"
                    f" · {_format_probability(recommendation.probability)}"
                )
                self.match_hint.setText("INTERCEPCIÓN EN EL PRÓXIMO CAMBIO")
            else:
                self.match_icon.setText("○")
                self.match_text.setText("PRÓXIMO MOVIMIENTO")
                self.match_hint.setText("RUTAS PROBABLES EN EL MAPA")
        else:
            self.match_icon.setText("○")
            self.match_text.setText("Movimiento no disponible")
            self.match_hint.setText("")

        self.match_banner.setToolTip(tooltip)
        self.match_banner.setProperty("matched", snapshot.same_area)
        self.match_banner.setProperty("mode", mode)
        self.match_banner.style().unpolish(self.match_banner)
        self.match_banner.style().polish(self.match_banner)

    def _show_species(self, species: RoamerSpecies) -> None:
        if species == self._displayed_species:
            return
        self._displayed_species = species
        name = species.name.upper()
        sprite_path = ROAMER_ASSETS[species]
        sprite = QPixmap(str(sprite_path)).scaled(
            58,
            58,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.roamer_sprite.setPixmap(sprite)
        self.roamer_heading.setText(name)
        self.roamer_legend_label.setText(name)
        self.setWindowTitle(f"Rastreador de {species.name}")
        self.setWindowIcon(QIcon(str(sprite_path)))

    def set_always_on_top(self, enabled: bool) -> None:
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
        if app is not None and app.platformName() != "offscreen":
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
        description="Ventana flotante para rastrear al roamer de Pokémon FireRed."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive_port, default=55355)
    parser.add_argument("--interval", type=positive_interval, default=0.20)
    args = parser.parse_args()

    app = QApplication([])
    app.setApplicationName("Rastreador de roamers")
    app.setQuitOnLastWindowClosed(True)
    window = TrackerWindow(args.host, args.port, args.interval)
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
        app.quit()

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
