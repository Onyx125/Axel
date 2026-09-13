"""Курсоры и подсказки при наведении на ручку (8.5).

Курсоры действий (перемещение, поворот, размер) убраны по замечанию пользователя: над
ручкой курсор обычный, над недоступной — «запрещено», снимается при уходе. Подсказка —
одной строкой в строке состояния FreeCAD после задержки ``TooltipDelayMs`` (всплывающая
``QToolTip`` перекрывала интерфейс — замечание пользователя): название ручки, действие,
модификаторы и, если есть, причина отключения; снимается, когда курсор уходит с ручки.
"""

from __future__ import annotations

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from ..core.i18n import tr
from ..core.intent import HandleId, HandleKind

AXIS_NAMES = ("X", "Y", "Z")
PLANE_NAMES = ("YZ", "XZ", "XY")

_HANDLE_TEXT: dict[HandleKind, tuple[str, str, str]] = {
    # название, действие, модификаторы — исходный язык английский (15.5)
    HandleKind.MOVE_AXIS: (
        "{axis} arrow",
        "drag to move along the axis, click to type a distance",
        "Ctrl — step, C C — copy",
    ),
    HandleKind.MOVE_PLANE: (
        "{plane} plane",
        "drag to move in the plane",
        "Ctrl — step, C C — copy",
    ),
    HandleKind.MOVE_FREE: (
        "Origin",
        "right-click for the menu",
        "double-click to relocate the origin",
    ),
    HandleKind.ROTATE: (
        "{axis} arc",
        "drag to rotate about the axis, click to type an angle",
        "Ctrl — step, C C — copy",
    ),
    HandleKind.SCALE_AXIS: (
        "{axis} scale",
        "drag to scale along the axis, click to type a factor",
        "Ctrl — step, Shift — uniform",
    ),
    HandleKind.EXTRUDE: (
        "{axis} extrude",
        "drag to extrude",
        "Shift — both directions",
    ),
}


def tooltip_text(handle: HandleId, disabled_reason: str = "") -> str:
    """Текст подсказки для ручки."""
    name, action, mods = _HANDLE_TEXT[handle.kind]
    axis = handle.axis if handle.axis is not None else 0
    name = tr(name).format(axis=AXIS_NAMES[axis], plane=PLANE_NAMES[axis])
    lines = [f"{name}: {tr(action)}"]
    if mods:
        lines.append(tr(mods))
    if disabled_reason:
        lines.append(tr("Unavailable: {}").format(disabled_reason))
    return "\n".join(lines)


def status_text(handle: HandleId, disabled_reason: str = "") -> str:
    """Та же подсказка одной строкой для строки состояния."""
    return "  ·  ".join(tooltip_text(handle, disabled_reason).splitlines())


class HoverFeedback:
    """Курсор и подсказка (в строке состояния) для viewport одного вида."""

    def __init__(
        self, viewport: QtWidgets.QWidget, delay_ms: int = 700, tooltips: bool = True
    ) -> None:
        """Обратная связь наведения на ``viewport``; подсказка через ``delay_ms``."""
        self.viewport = viewport
        self.delay_ms = delay_ms
        self.tooltips = tooltips
        self.handle: HandleId | None = None
        self._reason = ""
        self._pos = QtCore.QPoint()
        self._shown = False
        self._text = ""
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_tooltip)

    def update(self, handle: HandleId | None, qt_pos: QtCore.QPointF, reason: str = "") -> None:
        """Курсор над ручкой ``handle`` (или ``None``) в логических координатах viewport."""
        self._pos = qt_pos.toPoint()
        if handle != self.handle or reason != self._reason:
            self.handle = handle
            self._reason = reason
            self._hide_tooltip()
            if reason:
                self.viewport.setCursor(QtGui.QCursor(QtCore.Qt.ForbiddenCursor))
            else:
                self.viewport.unsetCursor()
        if handle is not None and self.tooltips and not self._shown:
            self._timer.start(self.delay_ms)

    def clear(self) -> None:
        """Снять курсор и подсказку (скрытие манипулятора, отвязка вида)."""
        self.update(None, QtCore.QPointF(self._pos))

    def _show_tooltip(self) -> None:
        if self.handle is None or not self.tooltips:
            return
        self._text = status_text(self.handle, self._reason)
        Gui.getMainWindow().statusBar().showMessage(self._text)
        self._shown = True

    def _hide_tooltip(self) -> None:
        self._timer.stop()
        if self._shown:
            bar = Gui.getMainWindow().statusBar()
            if bar.currentMessage() == self._text:  # чужое сообщение не трогаем
                bar.clearMessage()
            self._shown = False
