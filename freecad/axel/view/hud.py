"""Направляющие и подписи во время перетаскивания (8.4).

Направляющие — узлы Coin в мировых координатах внутри корня манипулятора (поверх геометрии,
без экранного масштаба): штриховая линия вдоль оси через всю видимую область и метка
исходного начала при перемещении; окружность и сектор при повороте. Подпись у курсора —
``QLabel`` поверх вьюера (текст Coin не используется: HiDPI и вид).
"""

from __future__ import annotations

import math

import FreeCAD as App
from pivy import coin
from PySide import QtCore, QtWidgets

from ..core.frame import Frame
from ..core.i18n import tr
from ..core.intent import HandleKind, Intent, Operation

Vector = App.Vector

GUIDE_COLOR = (0.35, 0.35, 0.35)
SECTOR_SEGMENTS = 48


def format_length(mm: float) -> str:
    """Длина в единицах пользователя со знаком (``UserString`` схемы FreeCAD)."""
    text = App.Units.Quantity(abs(mm), "mm").UserString
    return ("−" if mm < 0 else "") + text


def format_angle(rad: float) -> str:
    """Угол в градусах со знаком (``UserString`` схемы FreeCAD)."""
    deg = math.degrees(rad)
    text = App.Units.Quantity(abs(deg), "deg").UserString
    return ("−" if deg < 0 else "") + text


def format_factor(f: float) -> str:
    """Коэффициент масштаба: «×1.25»."""
    return f"×{f:.4g}"


def format_param(value: int | float | None, title: str) -> str:
    """Подпись ползунка: «Segments: 5» (9.2.2)."""
    if value is None:
        return title
    text = str(value) if isinstance(value, int) else f"{value:.4g}"
    return f"{title}: {text}" if title else text


AXIS_NAMES = ("X", "Y", "Z")


def format_label(intent: Intent, frame: Frame, prefix: str = "", param_title: str = "") -> str:
    """Текст подписи у курсора по таблице 8.4."""
    parts: list[str] = []
    if prefix:
        parts.append(prefix)
    kind = intent.handle.kind
    if intent.operation is Operation.PARAMETER:
        parts.append(format_param(intent.value, param_title))
    elif intent.operation is Operation.TRANSLATE:
        d = intent.translation
        if kind is HandleKind.MOVE_AXIS and intent.handle.axis is not None:
            parts.append(format_length(d.dot(frame.axis(intent.handle.axis))))
        elif kind is HandleKind.MOVE_PLANE and intent.handle.axis is not None:
            # «ΔX −18,51 mm  ΔY −33,60 mm  L 38,36 mm» (замечание пользователя)
            for i in sorted(i for i in range(3) if i != intent.handle.axis):  # X раньше Z
                parts.append(f"Δ{AXIS_NAMES[i]} {format_length(d.dot(frame.axis(i)))}")
            parts.append(f"L {format_length(d.Length)}")
        else:
            parts.append(format_length(d.Length))
    elif intent.operation is Operation.ROTATE:
        parts.append(format_angle(intent.angle))
    elif intent.operation is Operation.SCALE:
        if kind is HandleKind.SCALE_AXIS and intent.handle.axis is not None:
            f = intent.factors[intent.handle.axis]
        else:
            f = next((x for x in intent.factors if x != 1.0), 1.0)
        parts.append(format_factor(f))
        if kind is HandleKind.SCALE_AXIS and len(set(intent.factors)) == 1 and f != 1.0:
            parts.append(tr("uniform"))
    elif intent.operation is Operation.EXTRUDE:
        parts.append(format_length(intent.distance))
        if intent.both_sides:
            parts.append(tr("both sides"))
    if intent.copy:
        parts.append(tr("copy"))
    if intent.step:
        parts.append(tr("step"))
    return "  ".join(parts)


class Guides:
    """Узлы направляющих в сцене одного вида."""

    def __init__(self, parent: coin.SoSeparator) -> None:
        """Создать скрытый узел направляющих под ``parent`` (корень манипулятора)."""
        self.switch = coin.SoSwitch()
        self.switch.setName("ax_guides")
        self.switch.whichChild.setValue(-1)
        parent.addChild(self.switch)
        root = coin.SoSeparator()
        self.switch.addChild(root)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.0)
        style.linePattern.setValue(0xF0F0)
        root.addChild(style)
        color = coin.SoBaseColor()
        color.rgb.setValue(*GUIDE_COLOR)
        root.addChild(color)
        self.coords = coin.SoCoordinate3()
        root.addChild(self.coords)
        self.lines = coin.SoLineSet()
        root.addChild(self.lines)
        # сектор поворота: полупрозрачная заливка
        sector_root = coin.SoSeparator()
        root.addChild(sector_root)
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*GUIDE_COLOR)
        mat.transparency.setValue(0.75)
        sector_root.addChild(mat)
        fill_style = coin.SoDrawStyle()
        fill_style.linePattern.setValue(0xFFFF)
        sector_root.addChild(fill_style)
        self.sector_coords = coin.SoCoordinate3()
        sector_root.addChild(self.sector_coords)
        self.sector = coin.SoFaceSet()
        self.sector.numVertices.setValue(0)
        sector_root.addChild(self.sector)
        marker_root = coin.SoSeparator()
        root.addChild(marker_root)
        self.marker_coords = coin.SoCoordinate3()
        marker_root.addChild(self.marker_coords)
        markers = coin.SoMarkerSet()
        markers.markerIndex.setValue(coin.SoMarkerSet.CROSS_9_9)
        marker_root.addChild(markers)

    def hide(self) -> None:
        """Скрыть направляющие."""
        self.switch.whichChild.setValue(-1)

    def show_translate(
        self, origin0: Vector, origin: Vector, axis: Vector | None, extent: float
    ) -> None:
        """Штриховая линия вдоль оси (или от исходного начала к текущему) и метка начала."""
        if axis is not None:
            a, b = origin0 - axis * extent, origin0 + axis * extent
        else:
            a, b = origin0, origin
        self.coords.point.setValues(0, 2, [tuple(a), tuple(b)])
        self.lines.numVertices.setValues(0, 1, [2])
        self._set_markers([origin0])
        self.sector.numVertices.setValue(0)
        self.switch.whichChild.setValue(0)

    def show_axis(self, origin: Vector, axis: Vector, extent: float) -> None:
        """Штриховая линия вдоль оси без метки: масштаб и выдавливание (8.4)."""
        a, b = origin - axis * extent, origin + axis * extent
        self.coords.point.setValues(0, 2, [tuple(a), tuple(b)])
        self.lines.numVertices.setValues(0, 1, [2])
        self._set_markers([])
        self.sector.numVertices.setValue(0)
        self.switch.whichChild.setValue(0)

    def show_markers(self, points: list[Vector]) -> None:
        """Маркеры результата ползунка на объекте (8.4), без линий."""
        self.lines.numVertices.setValues(0, 1, [0])
        self.sector.numVertices.setValue(0)
        self._set_markers(points)
        self.switch.whichChild.setValue(0 if points else -1)

    def _set_markers(self, points: list[Vector]) -> None:
        self.marker_coords.point.setNum(len(points))
        if points:
            self.marker_coords.point.setValues(0, len(points), [tuple(p) for p in points])

    def show_rotate(
        self, center: Vector, axis: Vector, start: Vector, angle: float, radius: float
    ) -> None:
        """Полная окружность и сектор от начального до текущего угла."""
        u = start - center
        if u.Length == 0.0:
            return
        u = u.normalize()
        v = axis.cross(u)
        circle = [
            tuple(center + (u * math.cos(t) + v * math.sin(t)) * radius)
            for t in (2 * math.pi * i / SECTOR_SEGMENTS for i in range(SECTOR_SEGMENTS + 1))
        ]
        self.coords.point.setValues(0, len(circle), circle)
        self.lines.numVertices.setValues(0, 1, [len(circle)])
        n = max(2, int(abs(angle) / (2 * math.pi) * SECTOR_SEGMENTS) + 2)
        sector = [tuple(center)] + [
            tuple(center + (u * math.cos(t) + v * math.sin(t)) * radius)
            for t in (angle * i / (n - 1) for i in range(n))
        ]
        self.sector_coords.point.setValues(0, len(sector), sector)
        self.sector.numVertices.setValue(len(sector))
        self._set_markers([start])
        self.switch.whichChild.setValue(0)


class CursorLabel:
    """Подпись у курсора: ``QLabel`` поверх вьюера."""

    def __init__(self, viewer_widget: QtWidgets.QWidget, name: str = "axel_hud_label") -> None:
        """Скрытая подпись на виджете вьюера."""
        self.viewer = viewer_widget
        self.label = QtWidgets.QLabel(viewer_widget)
        self.label.setObjectName(name)
        self.label.setStyleSheet(
            "background: rgba(255, 255, 220, 230); color: #202020; border: 1px solid #909090;"
            " padding: 2px 6px; border-radius: 3px;"
        )
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.label.hide()

    def show(self, text: str, qt_pos: QtCore.QPointF) -> None:
        """Показать текст справа-снизу от точки (логические координаты вьюера)."""
        self.label.setText(text)
        self.label.adjustSize()
        x = int(qt_pos.x()) + 16
        y = int(qt_pos.y()) + 16
        x = max(0, min(x, self.viewer.width() - self.label.width()))
        y = max(0, min(y, self.viewer.height() - self.label.height()))
        self.label.move(x, y)
        self.label.show()
        self.label.raise_()

    def hide(self) -> None:
        """Скрыть подпись."""
        self.label.hide()
