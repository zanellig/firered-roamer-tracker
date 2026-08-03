"""PROTOTYPE — throwaway GUI variants for the roamer tracker window.

Question: what should the tracker window look like?

Four variants of the existing tracker window, switchable with `--variant`, the
floating bar at the bottom, or the ← / → keys:

    A  Pokédex       red dex shell, map as the dex screen, dot-leader entry
    B  Mapa          full-bleed map under the FRLG message box, text cycles
    C  Combate       battle HUD, the forecast is the 2x2 command menu
    D  Liquid Glass  blurred map backdrop, floating translucent panels

Run:

    uv run python src/roamer_tracker_prototype.py [--variant B]

Throwaway code: no tests, no error handling, no abstractions worth keeping.
It seeds the README's worked example so every variant is populated without
RetroArch running; live snapshots overwrite it as soon as they arrive.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import (  # noqa: E402
    ASSET_ROOT,
    CORAL,
    CYAN,
    GOLD,
    INK,
    ROAMER_ASSETS,
    WHITE,
    DragBar,
    KantoMap,
    TrackerThread,
    _format_probability,
    positive_interval,
    positive_port,
)
from tracker import (  # noqa: E402
    SUICUNE,
    Roamer,
    TrackerSnapshot,
    forecast_movement,
    location_for,
)

# The README's worked example: roamer on Route 22, player entering Viridian
# from Route 1, so Route 2 and Route 23 sit at 47,1% each.
_DEMO_ROAMER = location_for(3, 41)
_DEMO_PLAYER = location_for(3, 1)
DEMO_SNAPSHOT = TrackerSnapshot(
    roamer=Roamer(species=SUICUNE, location=_DEMO_ROAMER, active=True),
    player=_DEMO_PLAYER,
    same_area=False,
    forecast=forecast_movement(_DEMO_ROAMER, _DEMO_PLAYER, location_for(3, 19)),
)


# The region map inside the 240x160 asset, and its exact 2x size. Variants
# that want a full-bleed map crop the black GBA letterbox away.
MAP_CONTENT = QRectF(16, 16, 208, 144)
MAP_2X = (416, 288)
# Tighter still: drops the white paper border the game prints the map on.
MAP_INNER = QRectF(24, 16, 192, 144)
MAP_INNER_2X = (384, 288)


def pixel_font(size: int, *, bold: bool = False) -> QFont:
    font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
    font.setPixelSize(size)
    font.setBold(bold)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def sans_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(QApplication.font())
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def gba_text(
    painter: QPainter,
    rect: QRectF,
    align: Qt.AlignmentFlag,
    text: str,
    color: QColor = QColor("#404048"),
    shadow: QColor = QColor("#B8B8C8"),
) -> None:
    """GBA text is drawn twice: a light shadow one pixel down and right."""
    painter.setPen(shadow)
    painter.drawText(rect.translated(1, 1), align, text)
    painter.setPen(color)
    painter.drawText(rect, align, text)


def dot_row(painter: QPainter, rect: QRectF, label: str, value: str) -> None:
    metrics = painter.fontMetrics()
    dot_width = max(1, metrics.horizontalAdvance("."))
    free = (
        rect.width()
        - metrics.horizontalAdvance(label)
        - metrics.horizontalAdvance(value)
    )
    dots = "." * max(0, int(free - 12) // dot_width)
    gba_text(
        painter, rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label
    )
    gba_text(
        painter,
        rect,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        value,
    )
    gba_text(
        painter,
        rect,
        Qt.AlignmentFlag.AlignCenter,
        dots,
        QColor("#C0C0CC"),
        QColor("#F8F8F8"),
    )


def message_box(painter: QPainter, rect: QRectF) -> None:
    """The FRLG dialogue frame: white slab, blue rim, thin inner rule."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 60))
    painter.drawRoundedRect(rect.translated(4, 4), 7, 7)
    painter.setBrush(QColor("#F8F8F8"))
    painter.setPen(QPen(QColor("#4870B0"), 3))
    painter.drawRoundedRect(rect, 7, 7)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#A8C0E0"), 1))
    painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 4, 4)


def headline(snapshot: TrackerSnapshot) -> tuple[str, str]:
    if not snapshot.roamer.active:
        return "EL ROAMER NO ESTÁ ACTIVO", "Todavía no recorre Kanto"
    if snapshot.same_area:
        return "¡MISMA ZONA!", "Buscá en el pasto alto"
    recommendation = snapshot.forecast.recommendation if snapshot.forecast else None
    if recommendation is not None:
        return (
            f"CRUZÁ A {recommendation.route.name.upper()}",
            f"{_format_probability(recommendation.probability)} en el próximo cambio",
        )
    return "PRÓXIMO MOVIMIENTO", "Rutas probables en el mapa"


def route_chances(snapshot: TrackerSnapshot) -> list[tuple[str, float, bool]]:
    forecast = snapshot.forecast
    if forecast is None or not snapshot.roamer.active:
        return []
    recommended = (
        forecast.recommendation.route.number if forecast.recommendation else None
    )
    return [
        (
            chance.location.name.upper(),
            chance.probability,
            chance.location.number == recommended,
        )
        for chance in forecast.likely_routes
    ]


def blurred(pixmap: QPixmap, size: QSize, factor: int = 14) -> QPixmap:
    """Frosted backdrop on the cheap: downscale then upscale, both smoothed."""
    small = pixmap.scaled(
        max(1, size.width() // factor),
        max(1, size.height() // factor),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return small.scaled(
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class StyledMap(KantoMap):
    """KantoMap geometry with per-variant colours and marker shapes."""

    backdrop = INK
    frame_color = QColor("#304260")
    frame_width = 2
    frame_radius = 0
    player_color = CYAN
    roamer_color = CORAL
    route_color = GOLD
    chip_bg = QColor(16, 27, 45, 225)
    chip_fg = WHITE
    soft = False
    # Source window in GBA screen pixels. The asset is the whole 240x160
    # screen, so its black letterbox is only wanted inside the dex bezel.
    crop = QRectF(0, 0, 240, 160)

    def __init__(self, parent=None, size: tuple[int, int] = (480, 320)) -> None:
        super().__init__(parent)
        self.setFixedSize(*size)

    def _scaled(self, point: tuple[float, float]) -> tuple[float, float]:
        return (
            (point[0] - self.crop.x()) * self.width() / self.crop.width(),
            (point[1] - self.crop.y()) * self.height() / self.crop.height(),
        )

    def _route_rect(self, location) -> QRectF | None:
        bounds = location.map_bounds
        if bounds is None:
            return None
        scale_x = self.width() / self.crop.width()
        scale_y = self.height() / self.crop.height()
        return QRectF(
            (8 * bounds.x + 32 - self.crop.x()) * scale_x,
            (8 * bounds.y + 32 - self.crop.y()) * scale_y,
            8 * bounds.width * scale_x,
            8 * bounds.height * scale_y,
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        area = QRectF(self.rect())
        if self.frame_radius:
            clip = QPainterPath()
            clip.addRoundedRect(area, self.frame_radius, self.frame_radius)
            painter.setClipPath(clip)
        painter.fillRect(self.rect(), self.backdrop)
        painter.drawPixmap(area, self._map, self.crop)

        snapshot = self._snapshot
        if snapshot is not None:
            if (
                snapshot.roamer.active
                and not snapshot.same_area
                and snapshot.forecast is not None
            ):
                self._paint_routes(painter, snapshot)
            player = self._point(snapshot.player)
            roamer = self._point(snapshot.roamer.location)
            mark = snapshot.roamer.species.name[0]
            if snapshot.same_area and player is not None:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                x, y = self._scaled(player)
                painter.setBrush(
                    QColor(
                        self.route_color.red(),
                        self.route_color.green(),
                        self.route_color.blue(),
                        70,
                    )
                )
                painter.setPen(QPen(self.route_color, 3))
                painter.drawEllipse(QRectF(x - 19, y - 19, 38, 38))
                self._paint_marker(
                    painter, (player[0] - 2.5, player[1]), self.player_color, "V", False
                )
                self._paint_marker(
                    painter, (player[0] + 2.5, player[1]), self.roamer_color, mark, True
                )
            else:
                if snapshot.roamer.active and roamer is not None:
                    self._paint_marker(painter, roamer, self.roamer_color, mark, True)
                if player is not None:
                    self._paint_marker(painter, player, self.player_color, "V", False)

        painter.setClipping(False)
        if self.frame_width:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.frame_color, self.frame_width))
            inset = self.frame_width / 2
            edge = area.adjusted(inset, inset, -inset, -inset)
            if self.frame_radius:
                painter.drawRoundedRect(edge, self.frame_radius, self.frame_radius)
            else:
                painter.drawRect(edge)

    def _paint_routes(self, painter: QPainter, snapshot: TrackerSnapshot) -> None:
        forecast = snapshot.forecast
        recommended = (
            forecast.recommendation.route.number if forecast.recommendation else None
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, self.soft)
        taken: list[QRectF] = []
        for chance in forecast.likely_routes:
            rect = self._route_rect(chance.location)
            if rect is None:
                continue
            is_best = chance.location.number == recommended
            tint = QColor(self.route_color)
            tint.setAlpha(90 if is_best else 48)
            painter.setBrush(tint)
            painter.setPen(
                QPen(
                    self.route_color,
                    3 if is_best else 2,
                    Qt.PenStyle.SolidLine if is_best else Qt.PenStyle.DashLine,
                )
            )
            if self.soft:
                painter.drawRoundedRect(rect, 8, 8)
            else:
                painter.drawRect(rect)
            taken.append(
                self._paint_chip(painter, rect.center(), chance.probability, taken)
            )

    def _paint_chip(
        self,
        painter: QPainter,
        center: QPointF,
        probability: float,
        taken: list[QRectF],
    ) -> QRectF:
        base = QRectF(center.x() - 21, center.y() - 8, 42, 16)
        spot = base
        for dx, dy in ((0, 0), (0, -18), (0, 18), (-24, 0), (24, 0)):
            candidate = base.translated(dx, dy)
            if not any(candidate.intersects(other) for other in taken):
                spot = candidate
                break
        painter.setPen(QPen(self.route_color, 1))
        painter.setBrush(self.chip_bg)
        painter.drawRoundedRect(spot, 8 if self.soft else 3, 8 if self.soft else 3)
        painter.setFont(
            sans_font(9, QFont.Weight.DemiBold)
            if self.soft
            else pixel_font(9, bold=True)
        )
        painter.setPen(self.chip_fg)
        painter.drawText(
            spot, Qt.AlignmentFlag.AlignCenter, _format_probability(probability)
        )
        return spot

    def _paint_marker(
        self,
        painter: QPainter,
        point: tuple[float, float],
        color: QColor,
        label: str,
        diamond: bool,
    ) -> None:
        x, y = self._scaled(point)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.soft:
            glow = QRadialGradient(x, y, 22)
            glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 150))
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(x - 22, y - 22, 44, 44))
        painter.setPen(QPen(WHITE, 2))
        painter.setBrush(color)
        if diamond:
            painter.drawPolygon(
                [
                    QPointF(x, y - 10),
                    QPointF(x + 10, y),
                    QPointF(x, y + 10),
                    QPointF(x - 10, y),
                ]
            )
        else:
            painter.drawEllipse(QRectF(x - 9, y - 9, 18, 18))
        painter.setPen(WHITE)
        painter.setFont(
            sans_font(10, QFont.Weight.Bold) if self.soft else pixel_font(10, bold=True)
        )
        painter.drawText(
            QRectF(x - 9, y - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, label
        )


class Variant(QWidget):
    """Shared plumbing every variant gets: snapshot, connection, chrome."""

    KEY = "?"
    NAME = "sin nombre"
    SIZE = (512, 680)
    CHROME_QSS = ""
    CHROME_TOP_RIGHT = (12, 12)
    CHROME_SPACING = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.snapshot = DEMO_SNAPSHOT
        self.live = False
        self.setFixedSize(*self.SIZE)
        self.map = self.build_map()
        self.pin = QToolButton(self)
        self.pin.setText("◈")
        self.pin.setCheckable(True)
        self.pin.setChecked(True)
        self.pin.setToolTip("Mantener siempre visible")
        self.pin.toggled.connect(lambda on: self.window().toggle_pin(on))
        self.close_button = QToolButton(self)
        self.close_button.setText("✕")
        self.close_button.setToolTip("Cerrar")
        self.close_button.clicked.connect(lambda: self.window().close())
        for button in (self.pin, self.close_button):
            button.setStyleSheet(self.CHROME_QSS)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.place_chrome()

    def build_map(self) -> StyledMap | None:
        return None

    def place_chrome(self) -> None:
        right, top = self.CHROME_TOP_RIGHT
        x = self.width() - right
        for button in (self.close_button, self.pin):
            size = button.sizeHint()
            x -= size.width()
            button.move(x, top)
            x -= self.CHROME_SPACING

    def set_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self.snapshot = snapshot
        if self.map is not None:
            self.map.set_snapshot(snapshot)
        self.update()

    def set_connection(self, live: bool) -> None:
        self.live = live
        self.update()

    @property
    def status(self) -> str:
        return "EN VIVO" if self.live else "SIN CONEXIÓN"

    @property
    def status_color(self) -> QColor:
        return QColor("#58C858") if self.live else QColor("#E85040")

    def sprite(self, size: int) -> QPixmap:
        return QPixmap(str(ROAMER_ASSETS[self.snapshot.roamer.species])).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )


class DexMap(StyledMap):
    backdrop = QColor("#101820")
    frame_color = QColor("#000000")
    frame_width = 0
    chip_bg = QColor(16, 24, 32, 235)


class DexVariant(Variant):
    """A — the Pokédex shell. Map is the dex screen, data is a dex entry."""

    KEY = "A"
    NAME = "Pokédex"
    SIZE = (544, 792)
    CHROME_TOP_RIGHT = (24, 24)
    CHROME_QSS = """
        QToolButton {
            min-width: 26px; min-height: 26px;
            border: 2px solid #F8E0D8; border-radius: 15px;
            background: #781008; color: #F8E0D8;
            font-size: 12px; font-weight: 700;
        }
        QToolButton:hover { background: #A81810; }
        QToolButton:checked { background: #F8D048; color: #781008; border-color: #F8F8F8; }
    """

    def build_map(self) -> StyledMap:
        widget = DexMap(self)
        widget.move(32, 108)
        return widget

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_shell(painter)
        self._paint_lens(painter)
        self._paint_bezel(painter)
        self._paint_entry(painter)
        self._paint_controls(painter)

    def _paint_shell(self, painter: QPainter) -> None:
        body = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        shell = QLinearGradient(0, 0, 0, self.height())
        shell.setColorAt(0.0, QColor("#E03028"))
        shell.setColorAt(0.55, QColor("#C81810"))
        shell.setColorAt(1.0, QColor("#901008"))
        painter.setBrush(shell)
        painter.setPen(QPen(QColor("#600C06"), 2))
        painter.drawRoundedRect(body, 20, 20)
        painter.setPen(QPen(QColor(255, 190, 180, 110), 2))
        painter.drawLine(QPointF(20, 6), QPointF(self.width() - 20, 6))
        # Hinge between the screen half and the entry half.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#781008"))
        painter.drawRect(QRectF(24, 446, 496, 14))
        painter.setBrush(QColor("#F8C8C0"))
        for x in (44, 272, 500):
            painter.drawEllipse(QRectF(x - 3, 450, 6, 6))

    def _paint_lens(self, painter: QPainter) -> None:
        lens = QRadialGradient(52, 48, 30)
        lens.setColorAt(0.0, QColor("#B8ECFF"))
        lens.setColorAt(0.55, QColor("#3898E0"))
        lens.setColorAt(1.0, QColor("#0C4880"))
        painter.setBrush(lens)
        painter.setPen(QPen(QColor("#F8F8F8"), 4))
        painter.drawEllipse(QRectF(34, 32, 56, 56))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170))
        painter.drawEllipse(QRectF(46, 42, 16, 11))
        for index, color in enumerate(("#E85040", "#F8D048", "#58C858")):
            x = 108 + index * 26
            painter.setBrush(QColor(color))
            painter.setPen(QPen(QColor("#F8F8F8"), 2))
            painter.drawEllipse(QRectF(x, 50, 16, 16))
        painter.setFont(pixel_font(13, bold=True))
        title = QRectF(196, 38, 240, 20)
        painter.setPen(QColor("#7A0E06"))
        painter.drawText(
            title.translated(1, 1),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "POKéDEX · KANTO",
        )
        painter.setPen(QColor("#FFF0E8"))
        painter.drawText(
            title,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "POKéDEX · KANTO",
        )
        painter.setFont(pixel_font(10))
        painter.setPen(self.status_color)
        painter.drawText(
            QRectF(196, 58, 240, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "●",
        )
        painter.setPen(QColor("#FFE0D8"))
        painter.drawText(
            QRectF(208, 58, 240, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.status,
        )

    def _paint_bezel(self, painter: QPainter) -> None:
        painter.setBrush(QColor("#20202C"))
        painter.setPen(QPen(QColor("#101018"), 2))
        painter.drawRoundedRect(QRectF(24, 100, 496, 336), 8, 8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#585868"), 1))
        painter.drawRoundedRect(QRectF(28, 104, 488, 328), 6, 6)

    def _paint_entry(self, painter: QPainter) -> None:
        panel = QRectF(24, 470, 496, 252)
        message_box(painter, panel)
        painter.drawPixmap(44, 486, self.sprite(64))

        species = self.snapshot.roamer.species
        painter.setFont(pixel_font(21, bold=True))
        gba_text(
            painter,
            QRectF(120, 484, 260, 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            species.name.upper(),
            QColor("#282830"),
        )
        painter.setFont(pixel_font(11, bold=True))
        gba_text(
            painter,
            QRectF(320, 486, 180, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"N.º {species.id}",
            QColor("#787888"),
        )
        title, hint = headline(self.snapshot)
        painter.setFont(pixel_font(13, bold=True))
        gba_text(
            painter,
            QRectF(120, 512, 380, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
            QColor("#B02018"),
            QColor("#F0C8C0"),
        )
        painter.setFont(pixel_font(10))
        gba_text(
            painter,
            QRectF(120, 532, 380, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            hint,
            QColor("#787888"),
        )

        painter.setPen(QPen(QColor("#D8D8E0"), 1))
        painter.drawLine(QPointF(44, 558), QPointF(500, 558))
        painter.setFont(pixel_font(12))
        dot_row(
            painter,
            QRectF(44, 564, 456, 20),
            "ZONA",
            self.snapshot.roamer.location.name.upper()
            if self.snapshot.roamer.active
            else "INACTIVO",
        )
        dot_row(
            painter, QRectF(44, 586, 456, 20), "VOS", self.snapshot.player.name.upper()
        )
        painter.setPen(QPen(QColor("#D8D8E0"), 1))
        painter.drawLine(QPointF(44, 612), QPointF(500, 612))

        chances = route_chances(self.snapshot)[:4]
        painter.setFont(pixel_font(10, bold=True))
        gba_text(
            painter,
            QRectF(44, 618, 456, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "PRÓXIMO MOVIMIENTO" if chances else "SIN PRONÓSTICO",
            QColor("#4870B0"),
            QColor("#C8D8F0"),
        )
        painter.setFont(pixel_font(12))
        if not chances:
            gba_text(
                painter,
                QRectF(44, 646, 456, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hint,
                QColor("#909098"),
            )
        for index, (name, probability, best) in enumerate(chances):
            row = QRectF(44, 646 + index * 22, 456, 20)
            if best:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FFF0B8"))
                painter.drawRoundedRect(row.adjusted(-6, -1, 6, 1), 4, 4)
                gba_text(
                    painter,
                    QRectF(26, row.y(), 16, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    "▶",
                    QColor("#B02018"),
                    QColor("#F0C8C0"),
                )
            dot_row(painter, row, name, _format_probability(probability))

    def _paint_controls(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#301818"))
        for rect in (QRectF(46, 748, 48, 16), QRectF(62, 732, 16, 48)):
            painter.drawRoundedRect(rect, 3, 3)
        painter.setBrush(QColor("#F8D048"))
        painter.drawEllipse(QRectF(432, 738, 26, 26))
        painter.setBrush(QColor("#3898E0"))
        painter.drawEllipse(QRectF(470, 746, 20, 20))
        painter.setFont(pixel_font(9))
        painter.setPen(QColor(255, 220, 210, 150))
        painter.drawText(
            QRectF(120, 744, 280, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "SOLO LECTURA · RETROARCH",
        )


class TownMapWidget(StyledMap):
    backdrop = QColor("#184878")
    frame_color = QColor("#101828")
    frame_width = 3
    crop = MAP_CONTENT


class TownMapVariant(Variant):
    """B — the town map screen. Map is the whole window, text arrives as dialogue."""

    KEY = "B"
    NAME = "Mapa del pueblo"
    SIZE = (448, 472)
    PLATE = QRectF(16, 16, 416, 56)
    CHROME_QSS = """
        QToolButton {
            min-width: 22px; min-height: 22px;
            border: 2px solid #4870B0; border-radius: 4px;
            background: #F8F8F8; color: #404048;
            font-size: 11px; font-weight: 700;
        }
        QToolButton:hover { background: #D8E4F8; }
        QToolButton:checked { background: #4870B0; color: #F8F8F8; }
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page = 0
        self._caret = True
        self._pages_timer = QTimer(self)
        self._pages_timer.timeout.connect(self._advance)
        self._pages_timer.start(2600)
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._blink)
        self._caret_timer.start(450)

    def place_chrome(self) -> None:
        """Centre the buttons in the plate and leave room for the status."""
        right = int(self.PLATE.right()) - 12
        middle = int(self.PLATE.center().y())
        for button in (self.close_button, self.pin):
            size = button.sizeHint()
            right -= size.width()
            button.move(right, middle - size.height() // 2)
            right -= self.CHROME_SPACING
        self._status_right = right

    def build_map(self) -> StyledMap:
        widget = TownMapWidget(self, size=MAP_2X)
        widget.move(16, 84)
        return widget

    def _advance(self) -> None:
        self._page += 1
        self.update()

    def _blink(self) -> None:
        self._caret = not self._caret
        self.update()

    def pages(self) -> list[str]:
        snapshot = self.snapshot
        species = snapshot.roamer.species.name.upper()
        if not snapshot.roamer.active:
            return [
                f"{species} todavía no recorre KANTO.",
                "El rastreador sigue mirando.",
            ]
        if snapshot.same_area:
            return [
                f"¡{species} está en tu misma zona!",
                f"Buscá en {snapshot.player.name.upper()}.",
            ]
        lines = [
            f"{species} está en {snapshot.roamer.location.name.upper()}.\n"
            f"Vos estás en {snapshot.player.name.upper()}."
        ]
        chances = route_chances(snapshot)
        if chances:
            lines.append(
                "Próximo movimiento:\n"
                + "   ".join(
                    f"{name} {_format_probability(p)}" for name, p, _ in chances[:3]
                )
            )
        best = next((row for row in chances if row[2]), None)
        if best is not None:
            lines.append(
                f"¡Cruzá a {best[0]} ahora!\nLo interceptás en el próximo cambio."
            )
        return lines

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sky = QLinearGradient(0, 0, 0, self.height())
        sky.setColorAt(0.0, QColor("#3878C8"))
        sky.setColorAt(0.5, QColor("#204878"))
        sky.setColorAt(1.0, QColor("#102038"))
        painter.setBrush(sky)
        painter.setPen(QPen(QColor("#0C1828"), 2))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)

        message_box(painter, self.PLATE)
        painter.drawPixmap(26, 20, self.sprite(48))
        painter.setFont(pixel_font(15, bold=True))
        gba_text(
            painter,
            QRectF(84, 22, 240, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.roamer.species.name.upper(),
            QColor("#282830"),
        )
        painter.setFont(pixel_font(10, bold=True))
        gba_text(
            painter,
            QRectF(84, 46, 190, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.roamer.location.name.upper()
            if self.snapshot.roamer.active
            else "INACTIVO",
            QColor("#4870B0"),
            QColor("#C8D8F0"),
        )
        # Same row as the buttons, ending where place_chrome() left off.
        middle = self.PLATE.center().y()
        gba_text(
            painter,
            QRectF(200, middle - 9, self._status_right - 212, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"● {self.status}",
            self.status_color,
            QColor("#E0E4EC"),
        )

        box = QRectF(16, 388, 416, 68)
        message_box(painter, box)
        pages = self.pages()
        text = pages[self._page % len(pages)] if pages else ""
        painter.setFont(pixel_font(13))
        gba_text(
            painter,
            box.adjusted(18, 12, -26, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            text,
            QColor("#282830"),
        )
        if self._caret and len(pages) > 1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#4870B0"))
            tip = box.bottomRight()
            painter.drawPolygon(
                [
                    QPointF(tip.x() - 30, tip.y() - 22),
                    QPointF(tip.x() - 16, tip.y() - 22),
                    QPointF(tip.x() - 23, tip.y() - 13),
                ]
            )


class BattleMap(StyledMap):
    backdrop = QColor("#20303C")
    frame_color = QColor("#282830")
    frame_width = 3
    crop = MAP_CONTENT


class BattleVariant(Variant):
    """C — battle HUD. The forecast becomes the four-way command menu."""

    KEY = "C"
    NAME = "Combate"
    SIZE = (528, 668)
    CHROME_TOP_RIGHT = (16, 14)
    CHROME_QSS = """
        QToolButton {
            min-width: 24px; min-height: 24px;
            border: 2px solid #282830; border-radius: 4px;
            background: #F8F8F8; color: #282830;
            font-size: 11px; font-weight: 700;
        }
        QToolButton:hover { background: #FFE8A0; }
        QToolButton:checked { background: #F8D048; }
    """

    def build_map(self) -> StyledMap:
        widget = BattleMap(self, size=MAP_2X)
        widget.move(56, 178)
        return widget

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        field = QLinearGradient(0, 0, 0, 178)
        field.setColorAt(0.0, QColor("#98D0F8"))
        field.setColorAt(1.0, QColor("#D8F0F8"))
        painter.setBrush(field)
        painter.setPen(QPen(QColor("#101828"), 2))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        painter.setBrush(QColor("#20303C"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(4, 170, self.width() - 8, self.height() - 174))

        # Opponent platform and sprite, FRLG style: enemy up and to the right.
        painter.setBrush(QColor("#78C878"))
        painter.setPen(QPen(QColor("#409058"), 2))
        painter.drawEllipse(QRectF(352, 118, 136, 40))
        painter.drawPixmap(388, 66, self.sprite(72))

        self._enemy_box(painter)
        self._player_box(painter)
        self._command_menu(painter)

    def _slab(self, painter: QPainter, rect: QRectF, tint: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(rect.translated(4, 4), 10, 10)
        painter.setBrush(tint)
        painter.setPen(QPen(QColor("#282830"), 3))
        painter.drawRoundedRect(rect, 10, 10)

    def _bar(
        self, painter: QPainter, rect: QRectF, fraction: float, color: QColor
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#404048"))
        painter.drawRoundedRect(rect, 4, 4)
        filled = QRectF(rect)
        filled.setWidth(max(6.0, rect.width() * max(0.0, min(1.0, fraction))))
        painter.setBrush(color)
        painter.drawRoundedRect(filled.adjusted(2, 2, -2, -2), 3, 3)

    def _enemy_box(self, painter: QPainter) -> None:
        box = QRectF(16, 18, 296, 68)
        self._slab(painter, box, QColor("#F8F8E8"))
        painter.setFont(pixel_font(15, bold=True))
        gba_text(
            painter,
            QRectF(30, 24, 200, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.roamer.species.name.upper(),
            QColor("#282830"),
        )
        painter.setFont(pixel_font(10, bold=True))
        gba_text(
            painter,
            QRectF(200, 26, 96, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "SALVAJE",
            QColor("#B02018"),
            QColor("#F0C8C0"),
        )
        best = max((row[1] for row in route_chances(self.snapshot)), default=0.0)
        painter.setFont(pixel_font(9, bold=True))
        gba_text(
            painter,
            QRectF(30, 48, 40, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "PRB",
            QColor("#B08018"),
            QColor("#F8E8C0"),
        )
        self._bar(painter, QRectF(66, 52, 156, 12), best, QColor("#F8D048"))
        painter.setFont(pixel_font(10, bold=True))
        gba_text(
            painter,
            QRectF(228, 48, 70, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            _format_probability(best) if best else "—",
            QColor("#282830"),
        )

    def _player_box(self, painter: QPainter) -> None:
        box = QRectF(216, 476, 296, 58)
        self._slab(painter, box, QColor("#F8F8E8"))
        painter.setFont(pixel_font(10, bold=True))
        gba_text(
            painter,
            QRectF(232, 482, 120, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "VOS",
            QColor("#3878C8"),
            QColor("#C8D8F0"),
        )
        painter.setFont(pixel_font(9, bold=True))
        painter.setPen(self.status_color)
        painter.drawText(
            QRectF(360, 482, 136, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"● {self.status}",
        )
        painter.setFont(pixel_font(14, bold=True))
        gba_text(
            painter,
            QRectF(232, 500, 264, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.player.name.upper(),
            QColor("#282830"),
        )

    def _command_menu(self, painter: QPainter) -> None:
        prompt = QRectF(16, 476, 188, 58)
        self._slab(painter, prompt, QColor("#282830"))
        title, hint = headline(self.snapshot)
        painter.setFont(pixel_font(11, bold=True))
        painter.setPen(QColor("#F8D048"))
        painter.drawText(
            prompt.adjusted(12, 6, -10, -28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        painter.setFont(pixel_font(9))
        painter.setPen(QColor("#A8B8C8"))
        painter.drawText(
            prompt.adjusted(12, 30, -10, -6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            hint,
        )

        menu = QRectF(16, 546, 496, 106)
        self._slab(painter, menu, QColor("#F8F8F8"))
        chances = route_chances(self.snapshot)[:4]
        for index in range(4):
            column, row = index % 2, index // 2
            cell = QRectF(
                menu.x() + 14 + column * 238,
                menu.y() + 12 + row * 42,
                228,
                38,
            )
            if index >= len(chances):
                painter.setFont(pixel_font(12))
                gba_text(
                    painter,
                    cell,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    "  —",
                    QColor("#C0C0CC"),
                    QColor("#F8F8F8"),
                )
                continue
            name, probability, best = chances[index]
            if best:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FFE8A0"))
                painter.drawRoundedRect(cell.adjusted(-4, 0, 4, 0), 6, 6)
            painter.setFont(pixel_font(13, bold=True))
            gba_text(
                painter,
                cell.adjusted(22, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
                QColor("#282830"),
            )
            painter.setFont(pixel_font(12, bold=True))
            gba_text(
                painter,
                cell,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _format_probability(probability),
                QColor("#B02018") if best else QColor("#606070"),
                QColor("#F0D8D0") if best else QColor("#E0E0E8"),
            )
            if best:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#282830"))
                center = cell.center().y()
                painter.drawPolygon(
                    [
                        QPointF(cell.x(), center - 7),
                        QPointF(cell.x() + 11, center),
                        QPointF(cell.x(), center + 7),
                    ]
                )


class GlassMap(StyledMap):
    backdrop = QColor(10, 14, 22, 200)
    frame_color = QColor(255, 255, 255, 60)
    frame_width = 1
    frame_radius = 18
    player_color = QColor("#0A84FF")
    roamer_color = QColor("#FF375F")
    route_color = QColor("#FFD60A")
    chip_bg = QColor(20, 22, 30, 170)
    soft = True
    crop = MAP_INNER


class GlassVariant(Variant):
    """D — Apple Liquid Glass. Blurred map material under floating panels."""

    KEY = "D"
    NAME = "Liquid Glass"
    SIZE = (520, 704)
    CHROME_TOP_RIGHT = (28, 26)
    CHROME_SPACING = 8
    CHROME_QSS = """
        QToolButton {
            min-width: 30px; min-height: 30px;
            border: 1px solid rgba(255,255,255,0.45); border-radius: 15px;
            background: rgba(255,255,255,0.16); color: rgba(255,255,255,0.92);
            font-size: 12px;
        }
        QToolButton:hover { background: rgba(255,255,255,0.30); }
        QToolButton:checked {
            background: rgba(10,132,255,0.85);
            border-color: rgba(255,255,255,0.7);
            color: white;
        }
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._backdrop = blurred(
            QPixmap(str(ASSET_ROOT / "kanto_map.png")),
            QSize(*self.SIZE),
            factor=10,
        )

    def build_map(self) -> StyledMap:
        widget = GlassMap(self, size=MAP_INNER_2X)
        widget.move(68, 100)
        return widget

    def _glass(
        self, painter: QPainter, rect: QRectF, radius: float, alpha: int = 40
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(1, 5):
            painter.setBrush(QColor(0, 0, 0, 16))
            painter.drawRoundedRect(
                rect.adjusted(-step, -step + 3, step, step + 3),
                radius + step,
                radius + step,
            )
        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0.0, QColor(255, 255, 255, alpha + 34))
        sheen.setColorAt(0.45, QColor(255, 255, 255, alpha))
        sheen.setColorAt(1.0, QColor(255, 255, 255, max(10, alpha - 22)))
        painter.setBrush(sheen)
        painter.drawRoundedRect(rect, radius, radius)
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0.0, QColor(255, 255, 255, 190))
        rim.setColorAt(0.5, QColor(255, 255, 255, 60))
        rim.setColorAt(1.0, QColor(255, 255, 255, 130))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(rim, 1.2))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 30, 30)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, self._backdrop)
        wash = QLinearGradient(0, 0, 0, self.height())
        wash.setColorAt(0.0, QColor(14, 20, 34, 120))
        wash.setColorAt(1.0, QColor(6, 9, 18, 185))
        painter.fillRect(self.rect(), wash)

        toolbar = QRectF(16, 16, 488, 52)
        self._glass(painter, toolbar, 26)
        painter.setFont(sans_font(15, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(
            toolbar.adjusted(22, 0, -110, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Kanto Tracker",
        )
        painter.setFont(sans_font(11))
        painter.setPen(self.status_color)
        painter.drawText(
            toolbar.adjusted(150, 0, -110, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"● {self.status.title()}",
        )

        self._glass(painter, QRectF(16, 84, 488, 320), 26, alpha=30)
        self._roamer_card(painter)
        self._route_card(painter)
        self._segmented(painter)

    def _roamer_card(self, painter: QPainter) -> None:
        card = QRectF(16, 434, 488, 96)
        self._glass(painter, card, 26)
        painter.drawPixmap(38, 452, self.sprite(60))
        painter.setFont(sans_font(11, QFont.Weight.Medium))
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawText(
            QRectF(112, 452, 240, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.roamer.species.name.upper(),
        )
        painter.setFont(sans_font(22, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(
            QRectF(112, 468, 260, 30),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.snapshot.roamer.location.name
            if self.snapshot.roamer.active
            else "Inactivo",
        )
        painter.setFont(sans_font(11))
        painter.setPen(QColor(255, 255, 255, 160))
        painter.drawText(
            QRectF(112, 498, 260, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"Vos · {self.snapshot.player.name}",
        )
        recommendation = (
            self.snapshot.forecast.recommendation if self.snapshot.forecast else None
        )
        if recommendation is not None:
            action = f"Cruzá a {recommendation.route.name}"
        elif self.snapshot.same_area:
            action = "¡Misma zona!"
        else:
            action = "Sin cruce directo"
        pill = QRectF(340, 466, 146, 34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 132, 255, 190))
        painter.drawRoundedRect(pill, 17, 17)
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pill, 17, 17)
        painter.setFont(sans_font(11, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 245))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, action)

    def _route_card(self, painter: QPainter) -> None:
        card = QRectF(16, 542, 488, 106)
        self._glass(painter, card, 26, alpha=32)
        painter.setFont(sans_font(11, QFont.Weight.Medium))
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawText(
            QRectF(38, 552, 300, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Próximo movimiento",
        )
        for index, (name, probability, best) in enumerate(
            route_chances(self.snapshot)[:2]
        ):
            row = QRectF(38, 576 + index * 32, 444, 26)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.drawRoundedRect(row, 13, 13)
            filled = QRectF(row)
            filled.setWidth(row.width() * probability)
            painter.setBrush(
                QColor(255, 214, 10, 150) if best else QColor(255, 255, 255, 55)
            )
            painter.drawRoundedRect(filled, 13, 13)
            painter.setFont(sans_font(12, QFont.Weight.DemiBold))
            painter.setPen(QColor(255, 255, 255, 240))
            painter.drawText(
                row.adjusted(16, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name.title(),
            )
            painter.drawText(
                row.adjusted(0, 0, -16, 0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _format_probability(probability),
            )

    def _segmented(self, painter: QPainter) -> None:
        control = QRectF(140, 660, 240, 32)
        self._glass(painter, control, 16, alpha=34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 60))
        painter.drawRoundedRect(QRectF(143, 663, 78, 26), 13, 13)
        painter.setFont(sans_font(11, QFont.Weight.Medium))
        for index, label in enumerate(("Mapa", "Rutas", "Datos")):
            painter.setPen(QColor(255, 255, 255, 235 if index == 0 else 140))
            painter.drawText(
                QRectF(140 + index * 80, 660, 80, 32),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )


VARIANTS: list[type[Variant]] = [
    DexVariant,
    TownMapVariant,
    BattleVariant,
    GlassVariant,
]


class SwitcherBar(QFrame):
    """Deliberately ugly so nobody mistakes it for part of a variant."""

    def __init__(self, window: PrototypeWindow) -> None:
        super().__init__(window)
        self.host = window
        self.setStyleSheet(
            """
            QFrame { background: #0B0B0B; border: 2px solid #FF00A0; border-radius: 16px; }
            QLabel { color: #F8F8F8; font-size: 11px; font-weight: 700; background: transparent; border: 0; }
            QToolButton {
                min-width: 24px; min-height: 24px; border: 0; border-radius: 12px;
                background: #FF00A0; color: #0B0B0B; font-size: 13px; font-weight: 900;
            }
            QToolButton:hover { background: #FF66C4; }
            """
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)
        previous = QToolButton(self)
        previous.setText("◀")
        previous.clicked.connect(lambda: window.cycle(-1))
        following = QToolButton(self)
        following.setText("▶")
        following.clicked.connect(lambda: window.cycle(1))
        self.label = QLabel("", self)
        self.label.setMinimumWidth(160)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(previous)
        row.addWidget(self.label)
        row.addWidget(following)

    HEIGHT = 52

    def show_variant(self, variant: Variant) -> None:
        self.label.setText(f"{variant.KEY} — {variant.NAME}")
        self.adjustSize()
        self.move(
            (self.host.width() - self.width()) // 2,
            variant.height() + (self.HEIGHT - self.height()) // 2,
        )
        self.raise_()


class PrototypeWindow(DragBar):
    """Frameless host: drag anywhere, swap the variant underneath."""

    def __init__(self, host: str, port: int, interval: float, key: str) -> None:
        super().__init__()
        self.setWindowTitle("PROTOTIPO — Rastreador de roamers")
        self.setWindowIcon(QIcon(str(ASSET_ROOT / "app_icon.png")))
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QFrame { background: transparent; }")
        self.snapshot = DEMO_SNAPSHOT
        self.live = False
        self.variant: Variant | None = None
        self.switcher = SwitcherBar(self)
        self.show_variant(key)

        self.worker = TrackerThread(host, port, interval, self)
        self.worker.snapshot_ready.connect(self.on_snapshot)
        self.worker.connection_changed.connect(self.on_connection)
        self.worker.start()

    def show_variant(self, key: str) -> None:
        chosen = next((cls for cls in VARIANTS if cls.KEY == key.upper()), VARIANTS[0])
        if self.variant is not None:
            self.variant.hide()
            self.variant.deleteLater()
        self.variant = chosen(self)
        self.variant.move(0, 0)
        self.variant.set_snapshot(self.snapshot)
        self.variant.set_connection(self.live)
        # The switcher lives in a transparent strip below the variant so it
        # never covers the design being judged.
        self.setFixedSize(chosen.SIZE[0], chosen.SIZE[1] + SwitcherBar.HEIGHT)
        self.variant.show()
        self.switcher.show_variant(self.variant)
        print(f"[prototipo] variante {chosen.KEY} — {chosen.NAME}")

    def cycle(self, step: int) -> None:
        keys = [cls.KEY for cls in VARIANTS]
        index = keys.index(self.variant.KEY)
        self.show_variant(keys[(index + step) % len(keys)])

    def toggle_pin(self, enabled: bool) -> None:
        position = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self.move(position)

    def on_snapshot(self, snapshot: TrackerSnapshot) -> None:
        self.snapshot = snapshot
        self.variant.set_snapshot(snapshot)

    def on_connection(self, live: bool) -> None:
        self.live = live
        self.variant.set_connection(live)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.cycle(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.cycle(1)
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive_port, default=55355)
    parser.add_argument("--interval", type=positive_interval, default=0.20)
    parser.add_argument(
        "--variant",
        default="A",
        choices=[cls.KEY for cls in VARIANTS] + [cls.KEY.lower() for cls in VARIANTS],
    )
    args = parser.parse_args()

    app = QApplication([])
    app.setApplicationName("PROTOTIPO — Rastreador de roamers")
    window = PrototypeWindow(args.host, args.port, args.interval, args.variant)

    interrupt_timer = QTimer()
    interrupt_timer.setInterval(200)
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start()
    signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, window.close))

    window.show()
    window.setFocus()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
