"""Always-on-top desktop GUI for the FireRed Suicune RAM tracker."""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
from threading import Event

from PySide6.QtCore import QPoint, QRectF, Qt, QThread, QTimer, Signal
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
        Location,
        RetroArchNCI,
        TrackerError,
        TrackerSnapshot,
        read_snapshot,
    )
else:
    from tracker import Location, RetroArchNCI, TrackerError, TrackerSnapshot, read_snapshot


APP_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = APP_ROOT / "assets"

NAVY = QColor("#172640")
INK = QColor("#101b2d")
CYAN = QColor("#49b8d0")
CORAL = QColor("#e2554d")
GOLD = QColor("#f1c84b")
WHITE = QColor("#fff9e8")


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
        self.setAccessibleName("Mapa de Kanto con la ubicación de Suicune y del jugador")
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
            player = self._point(self._snapshot.player)
            suicune = self._point(self._snapshot.suicune)
            if self._snapshot.same_area and player is not None:
                self._draw_match(painter, player)
            else:
                if suicune is not None:
                    self._draw_marker(painter, suicune, CORAL, "S", diamond=True)
                if player is not None:
                    self._draw_marker(painter, player, CYAN, "V")

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#304260"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def _scaled(self, point: tuple[float, float]) -> tuple[float, float]:
        return point[0] * self.width() / 240, point[1] * self.height() / 160

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

    def _draw_match(self, painter: QPainter, point: tuple[float, float]) -> None:
        x, y = self._scaled(point)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(241, 200, 75, 70))
        painter.setPen(QPen(GOLD, 3))
        painter.drawEllipse(QRectF(x - 18, y - 18, 36, 36))
        self._draw_marker(painter, (point[0] - 2.5, point[1]), CYAN, "V")
        self._draw_marker(painter, (point[0] + 2.5, point[1]), CORAL, "S", diamond=True)


class TrackerWindow(QWidget):
    def __init__(
        self,
        host: str,
        port: int,
        interval: float,
        *,
        start_worker: bool = True,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.setObjectName("shell")
        self.setWindowTitle("Rastreador de Suicune")
        self.setWindowIcon(QIcon(str(ASSET_ROOT / "app_icon.png")))
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
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
        legend.addWidget(self._legend("◆", "SUICUNE", "suicune"))
        legend.addStretch()
        map_note = QLabel("MAPA ORIGINAL · FIRERED")
        map_note.setObjectName("mapNote")
        legend.addWidget(map_note)
        layout.addLayout(legend)

        self.match_banner = QFrame()
        self.match_banner.setObjectName("matchBanner")
        self.match_banner.setProperty("matched", False)
        match_layout = QHBoxLayout(self.match_banner)
        match_layout.setContentsMargins(12, 8, 12, 8)
        match_layout.setSpacing(8)
        self.match_icon = QLabel("○")
        self.match_icon.setObjectName("matchIcon")
        self.match_text = QLabel("Todavía no comparten zona")
        self.match_text.setObjectName("matchText")
        self.match_hint = QLabel("Cambiá de área para mover al roamer")
        self.match_hint.setObjectName("matchHint")
        match_layout.addWidget(self.match_icon)
        match_layout.addWidget(self.match_text)
        match_layout.addStretch()
        match_layout.addWidget(self.match_hint)
        layout.addWidget(self.match_banner)

        locations = QHBoxLayout()
        locations.setSpacing(10)
        self.suicune_location = QLabel("—")
        self.player_location = QLabel("—")
        locations.addWidget(
            self._location_card(
                "SUICUNE",
                self.suicune_location,
                "suicuneCard",
                ASSET_ROOT / "suicune.png",
            ),
            3,
        )
        locations.addWidget(
            self._location_card("VOS", self.player_location, "playerCard"),
            2,
        )
        layout.addLayout(locations)
        root.addWidget(content)

    def _legend(self, symbol: str, text: str, tone: str) -> QWidget:
        item = QWidget()
        row = QHBoxLayout(item)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        icon = QLabel(symbol)
        icon.setObjectName(f"{tone}Legend")
        label = QLabel(text)
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
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(object_name)
        row = QHBoxLayout(card)
        row.setContentsMargins(11, 8, 11, 8)
        row.setSpacing(9)
        if sprite_path is not None:
            sprite = QLabel()
            sprite.setObjectName("suicuneSprite")
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
        heading = QLabel(title)
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
            QLabel#endpoint, QLabel#mapNote {{ color: #7387a1; font-size: 9px; }}
            QLabel#playerLegend {{ color: #49b8d0; font-size: 15px; }}
            QLabel#suicuneLegend {{ color: #e2554d; font-size: 15px; }}
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
            QLabel#matchIcon {{ color: #7387a1; font-size: 19px; }}
            QFrame#matchBanner[matched="true"] QLabel#matchIcon {{ color: #f1c84b; }}
            QLabel#matchText {{ color: #dce5ec; font-size: 11px; font-weight: 700; }}
            QFrame#matchBanner[matched="true"] QLabel#matchText {{ color: #fff4b0; }}
            QLabel#matchHint {{ color: #7387a1; font-size: 9px; }}
            QFrame#suicuneCard, QFrame#playerCard {{
                background: #172640;
                border: 1px solid #304260;
                border-radius: 8px;
            }}
            QFrame#suicuneCard {{ border-left: 3px solid #e2554d; }}
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
        self.map.set_snapshot(snapshot)
        self.suicune_location.setText(snapshot.suicune.name)
        self.player_location.setText(snapshot.player.name)
        self.match_banner.setProperty("matched", snapshot.same_area)
        self.match_banner.style().unpolish(self.match_banner)
        self.match_banner.style().polish(self.match_banner)
        if snapshot.same_area:
            self.match_icon.setText("◎")
            self.match_text.setText("¡MISMA ZONA!")
            self.match_hint.setText("Caminá en el pasto")
        else:
            self.match_icon.setText("○")
            self.match_text.setText("Todavía no comparten zona")
            self.match_hint.setText("Cambiá de área para mover al roamer")

    def set_always_on_top(self, enabled: bool) -> None:
        position = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        # Qt hides a top-level widget when a window flag changes.
        self.show()
        self.move(position)

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
        description="Ventana flotante para rastrear a Suicune en Pokémon FireRed."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive_port, default=55355)
    parser.add_argument("--interval", type=positive_interval, default=0.20)
    args = parser.parse_args()

    app = QApplication([])
    app.setApplicationName("Rastreador de Suicune")
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
