"""Кнопка «Axel» в строке состояния (15.2).

Стоит первой среди постоянных виджетов — левее кнопок FreeCAD (замечание
пользователя). Переключатель шага из строки состояния убран (замечание пользователя): шаг —
в меню манипулятора, командой `Axel_Step` и клавишей Ctrl.
"""

from __future__ import annotations

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from ..core.i18n import tr
from ..runtime import get_runtime
from .commands import icon

_button: QtWidgets.QToolButton | None = None
_container: QtWidgets.QWidget | None = None


def install() -> QtWidgets.QToolButton:
    """Добавить кнопку в строку состояния главного окна; повторный вызов вернёт существующую."""
    global _button
    if _button is not None:
        return _button
    runtime = get_runtime()
    button = QtWidgets.QToolButton()
    button.setObjectName("axel_statusbar_toggle")
    button.setText("Axel")
    button.setIcon(QtGui.QIcon(icon("Axel")))
    button.setToolButtonStyle(QtGui.Qt.ToolButtonTextBesideIcon)
    button.setCheckable(True)
    button.setChecked(runtime.enabled)
    button.setToolTip(tr("Axel: object manipulator — turn on or off"))
    button.toggled.connect(_on_toggled)
    button.setContextMenuPolicy(QtGui.Qt.CustomContextMenu)
    button.customContextMenuRequested.connect(_on_context_menu)
    runtime.add_listener(lambda enabled: button.setChecked(enabled))
    _place(button)
    _button = button
    return button


def _place(button: QtWidgets.QToolButton) -> None:
    """Кнопка первой среди постоянных виджетов строки состояния."""
    global _container
    button.setAutoRaise(True)
    _container = button
    # При InitGui строка состояния ещё не собрана (подписи сообщения и подсказки появляются
    # позже), и вставка попадает не туда — ставим после запуска цикла событий. Draft при
    # активации вставляет привязки и масштаб по жёстким индексам 2 и 3 (масштаб — через
    # 500 мс), то есть тоже первыми среди постоянных, поэтому после каждой активации
    # верстака кнопка переставляется снова, с запасом по времени.
    _schedule_insert(0)
    Gui.getMainWindow().workbenchActivated.connect(lambda _name: _schedule_insert(REINSERT_MS))


REINSERT_MS = 800  # больше 500 мс задержки Draft


def _schedule_insert(delay_ms: int) -> None:
    QtCore.QTimer.singleShot(delay_ms, _insert_container)


def _insert_container() -> None:
    """Поставить кнопку первой среди постоянных виджетов строки состояния."""
    if _container is None:
        return
    bar = Gui.getMainWindow().statusBar()
    bar.removeWidget(_container)
    bar.insertPermanentWidget(_first_permanent_index(bar), _container)
    _container.show()


def _first_permanent_index(bar: QtWidgets.QStatusBar) -> int:
    """Индекс для ``insertPermanentWidget``, ставящий виджет первым среди постоянных.

    Qt считает индекс по всем элементам строки, включая обычные (у FreeCAD это подписи
    сообщения и подсказки), и при индексе не больше последнего обычного молча добавляет в
    конец. Число обычных виджетов читается из внутренней раскладки строки — той вложенной,
    где лежат сами виджеты: ``[отступ, обычные…, растяжка, постоянные…, отступ]`` — виджеты
    между первой и второй распорками.
    """
    layouts = [bar.layout()]
    while layouts:
        lay = layouts.pop()
        if lay is None:
            continue
        items = [lay.itemAt(i) for i in range(lay.count())]
        layouts.extend(item.layout() for item in items if item.layout() is not None)
        if not any(item.widget() is not None for item in items):
            continue
        spacers, widgets = 0, 0
        for item in items:
            if item.widget() is not None:
                if spacers == 1:
                    widgets += 1
            elif item.spacerItem() is not None:
                spacers += 1
                if spacers == 2:
                    return widgets
    return 0


def _on_context_menu(pos: object) -> None:
    """ПКМ по кнопке — меню манипулятора (15.2)."""
    from .menu import show_menu

    if _button is not None:
        show_menu(_button, None)


def _on_toggled(checked: bool) -> None:
    runtime = get_runtime()
    if checked != runtime.enabled:
        runtime.toggle()
