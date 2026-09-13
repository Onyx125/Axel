"""Меню манипулятора (9.5, F-24): ``QMenu`` у курсора.

Открывается щелчком по кружку меню или ПКМ по началу. Пункты дублируют команды
``gui.commands`` и настройки; пункты этапов 3–4 (операции, страница настроек,
выравнивание по виду) присутствуют, но выключены.
"""

from __future__ import annotations

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from ..adapters.base import STANDARD_OPERATIONS
from ..core.i18n import tr
from ..core.intent import HandleKind
from ..runtime import get_runtime, params
from . import commands, preferences

DRAG_STRENGTHS = (100, 50, 25, 10)

# Подписи групп ручек; состав групп — preferences.HANDLE_GROUP_KEYS (15.4 «Ручки»)
HANDLE_GROUP_TEXT: dict[str, str] = {
    "ShowMove": "Move arrows",
    "ShowMove2D": "Plane handles",
    "ShowRotate": "Rotation arcs",
    "ShowScale": "Scale handles",
    "ShowExtrude": "Extrude dots",
}


def build_menu(parent: QtWidgets.QWidget | None = None) -> QtWidgets.QMenu:
    """Собрать меню по текущему состоянию контроллера и настроек."""
    runtime = get_runtime()
    ctl = runtime.controller
    settings = runtime.settings
    menu = QtWidgets.QMenu(parent)
    menu.setObjectName("axel_menu")
    menu.setAttribute(QtCore.Qt.WA_DeleteOnClose)

    act = menu.addAction(tr("Relocate the origin"))
    act.setEnabled(ctl is not None and ctl.visible)
    act.triggered.connect(lambda: ctl.start_relocate())
    act = menu.addAction(tr("Reset the frame"))
    act.setEnabled(ctl is not None and ctl.visible)
    act.triggered.connect(lambda: ctl.reset_frame())

    subs: list[QtWidgets.QMenu] = []  # ссылки на подменю: обёртки PySide иначе теряются

    def submenu(title: str) -> QtWidgets.QMenu:
        sub = QtWidgets.QMenu(title, menu)
        menu.addMenu(sub)
        subs.append(sub)
        return sub

    align = submenu(tr("Alignment"))
    group = QtGui.QActionGroup(align)
    for name, (alignment, text, _tip) in commands.ALIGN_COMMANDS.items():
        act = align.addAction(tr(text).removeprefix("Axel: ").capitalize())
        act.setCheckable(True)
        act.setChecked(ctl is not None and ctl.alignment is alignment)
        act.triggered.connect(lambda _=False, n=name: Gui.runCommand(n))
        group.addAction(act)

    act = menu.addAction(tr("Auto reset"))
    act.setCheckable(True)
    act.setChecked(settings.auto_reset)
    act.triggered.connect(lambda: Gui.runCommand(commands.AutoResetCommand.name))
    act = menu.addAction(tr("Step"))
    act.setCheckable(True)
    act.setChecked(settings.step_enabled)
    act.triggered.connect(lambda: Gui.runCommand(commands.StepCommand.name))

    ops = submenu(tr("Operations"))
    specs = {spec.id: spec for spec in ctl.operations()} if ctl is not None else {}
    entries = [
        (op_id, tr(text).removeprefix("Axel: "))
        for op_id, text, _tip in commands.OPERATION_COMMANDS
    ]
    entries += [
        (op_id, tr(specs[op_id].title) if op_id in specs else op_id)
        for op_id in commands.operation_letters()
        if op_id not in STANDARD_OPERATIONS  # операции адаптеров верстаков (15.1)
    ]
    for op_id, text in entries:
        letter = commands.operation_letters().get(op_id, "")
        act = ops.addAction(text[:1].upper() + text[1:])
        act.setCheckable(True)
        act.setChecked(ctl is not None and ctl.armed_op == op_id)
        act.setEnabled(op_id in specs)
        if letter:
            act.setShortcut(QtGui.QKeySequence(f"{letter}, {letter}"))
        act.triggered.connect(lambda _=False, i=op_id: _arm(i))

    strength = submenu(tr("Drag strength"))
    group = QtGui.QActionGroup(strength)
    for percent in DRAG_STRENGTHS:
        act = strength.addAction(f"{percent} %")
        act.setCheckable(True)
        act.setChecked(int(settings.drag_strength_percent) == percent)
        act.triggered.connect(lambda _=False, p=percent: _set_strength(p))
        group.addAction(act)

    handles = submenu(tr("Handles"))
    for key, kinds in preferences.HANDLE_GROUP_KEYS.items():
        act = handles.addAction(tr(HANDLE_GROUP_TEXT[key]))
        act.setCheckable(True)
        act.setChecked(bool(kinds & settings.shown_kinds))
        act.triggered.connect(lambda checked, k=key, ks=kinds: _set_handles(k, ks, checked))

    menu.addSeparator()
    act = menu.addAction(tr("Settings…"))
    act.triggered.connect(lambda: Gui.runCommand(commands.SettingsCommand.name))
    act = menu.addAction(tr("Turn Axel off"))
    act.triggered.connect(lambda: Gui.runCommand(commands.ToggleCommand.name))
    menu.submenus = subs  # type: ignore[attr-defined]
    return menu


def show_menu(viewport: QtWidgets.QWidget, qt_pos: QtCore.QPointF | None) -> None:
    """Показать меню у точки ``qt_pos`` (логические координаты ``viewport``) или у курсора."""
    menu = build_menu(viewport)
    if qt_pos is None:
        global_pos = QtGui.QCursor.pos()
    else:
        global_pos = viewport.mapToGlobal(qt_pos.toPoint())
    menu.popup(global_pos)  # не exec: модальный цикл мешал бы граббер-событиям Coin


def _arm(op_id: str) -> None:
    controller = get_runtime().controller
    if controller is not None:
        controller.arm_operation(op_id)


def _set_strength(percent: int) -> None:
    runtime = get_runtime()
    runtime.settings.drag_strength_percent = float(percent)
    params().SetInt("DragStrength", percent)


def _set_handles(key: str, kinds: frozenset[HandleKind], on: bool) -> None:
    runtime = get_runtime()
    shown = set(runtime.settings.shown_kinds)
    shown = shown | kinds if on else shown - kinds
    runtime.settings.shown_kinds = frozenset(shown)
    runtime.save_setting(key, on)
    if runtime.controller is not None:
        runtime.controller.refresh()
