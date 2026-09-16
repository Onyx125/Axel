"""Поле числового ввода поверх 3D-вида (9.3, F-11, F-12).

Виджет — ``Gui::InputField`` через ``Gui.UiLoader`` (единицы и выражения как в редакторе
свойств), запасной вариант — ``QLineEdit`` с разбором ``App.Units.Quantity``. Дочерний
виджет вьюера ``Gui::View3DInventorViewer``; пока поле в фокусе, сочетания FreeCAD не
срабатывают (``ShortcutManager``, С-6).
"""

from __future__ import annotations

from collections.abc import Callable

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from ..core.i18n import tr

LENGTH = "length"
ANGLE = "angle"
FACTOR = "factor"
NUMBER = "number"  # значение ползунка (9.2.2): безразмерное число


def parse_value(text: str, kind: str) -> float:
    """Строка → число в единицах ядра: мм для длины, градусы для угла, коэффициент.

    Безразмерное значение трактуется в мм / градусах (схема Internal). Некорректный ввод —
    ``ValueError``.
    """
    text = text.strip()
    if not text:
        raise ValueError("пустой ввод")
    try:
        q = App.Units.Quantity(text)
    except Exception as exc:  # «syntax error» FreeCAD
        raise ValueError(f"не число: {text!r}") from exc
    unit_type = q.Unit.Type
    dimensionless = q.Unit == App.Units.Unit()  # у безразмерной величины Unit.Type == "1"
    if kind == LENGTH:
        if unit_type == "Length":
            return float(q.getValueAs("mm"))  # getValueAs возвращает Quantity
        if dimensionless:
            return float(q.Value)
        raise ValueError(f"нужна длина, а не {unit_type}")
    if kind == ANGLE:
        if unit_type == "Angle":
            return float(q.getValueAs("deg"))
        if dimensionless:
            return float(q.Value)
        raise ValueError(f"нужен угол, а не {unit_type}")
    if not dimensionless:
        raise ValueError("коэффициент — безразмерное число")
    return float(q.Value)


class NumericField(QtCore.QObject):
    """Поле ввода у ручки: Enter — принять, Esc или потеря фокуса — отменить."""

    def __init__(self, parent_widget: QtWidgets.QWidget) -> None:
        """Создать поле (скрытое) на виджете вьюера."""
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.kind = LENGTH
        self.on_accept: Callable[[float], None] | None = None
        self.on_cancel: Callable[[], None] | None = None
        self._active = False
        self.widget = self._create(parent_widget)
        self.widget.hide()
        self.widget.installEventFilter(self)

    @staticmethod
    def _create(parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        widget = None
        try:
            widget = Gui.UiLoader().createWidget("Gui::InputField")
        except Exception:  # noqa: BLE001
            widget = None
        if widget is None:
            widget = QtWidgets.QLineEdit()
        widget.setParent(parent)
        widget.setObjectName("axel_numeric_field")
        widget.setFixedWidth(140)
        return widget

    # ------------------------------------------------------------------ показ

    def show(
        self,
        kind: str,
        initial: str,
        qt_pos: QtCore.QPointF,
        on_accept: Callable[[float], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Показать поле у точки ``qt_pos`` (логические координаты вьюера)."""
        self.kind = kind
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self._active = True
        w = self.widget
        w.setStyleSheet("")
        w.setToolTip(
            {
                LENGTH: tr("Length, millimetres by default"),
                ANGLE: tr("Angle in degrees"),
                FACTOR: tr("Factor"),
                NUMBER: tr("Value"),
            }.get(kind, "")
        )
        x = int(qt_pos.x()) + 12
        y = int(qt_pos.y()) - w.sizeHint().height() // 2
        x = max(0, min(x, self.parent_widget.width() - w.width()))
        y = max(0, min(y, self.parent_widget.height() - w.sizeHint().height()))
        w.move(x, y)
        w.show()
        w.raise_()
        w.setFocus()
        # текст — только после show(): при показе InputField переформатирует содержимое
        # («3» → «3,00», и набор « cm» после начатой цифры давал «3 cm,00»); у показанного
        # поля setText текст не трогает (доводка 17.09.2026, снято при записи d26)
        if hasattr(w, "setText"):
            w.setText(initial)
        else:
            w.setProperty("text", initial)
        if initial and hasattr(w, "setCursorPosition"):
            w.setCursorPosition(len(initial))  # продолжать набор после начатой цифры (F-12)
        elif hasattr(w, "selectAll"):
            w.selectAll()

    @property
    def active(self) -> bool:
        """Поле показано и ждёт ввода."""
        return self._active

    def text(self) -> str:
        """Текущий текст поля."""
        return str(self.widget.property("text") or "")

    # ------------------------------------------------------------------ завершение

    def accept(self) -> bool:
        """Enter: разобрать значение; при ошибке подсветить поле и остаться."""
        if not self._active:
            return False
        try:
            value = parse_value(self.text(), self.kind)
        except ValueError:
            self.widget.setStyleSheet("border: 2px solid #d03030;")
            return False
        callback = self.on_accept
        self._close()
        if callback is not None:
            callback(value)
        return True

    def cancel(self) -> None:
        """Esc или потеря фокуса."""
        if not self._active:
            return
        callback = self.on_cancel
        self._close()
        if callback is not None:
            callback()

    def _close(self) -> None:
        self._active = False
        self.on_accept = None
        self.on_cancel = None
        self.widget.hide()
        self.parent_widget.setFocus()  # сочетания FreeCAD снова работают (9.3)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Enter/Esc в поле; потеря фокуса — отмена на следующем цикле событий."""
        if not self._active:
            return False
        kind = event.type()
        if kind == QtCore.QEvent.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.accept()
                return True
            if key == QtCore.Qt.Key_Escape:
                self.cancel()
                return True
        elif kind == QtCore.QEvent.FocusOut:
            QtCore.QTimer.singleShot(0, self._cancel_if_unfocused)
        return False

    def _cancel_if_unfocused(self) -> None:
        if self._active and not self.widget.hasFocus():
            self.cancel()
