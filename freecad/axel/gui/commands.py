"""Команды FreeCAD (15.1) и встраивание в меню и панели всех верстаков (13.1).

Этап 1: ``Axel_Toggle``. Остальные команды добавляются по этапам. Команды регистрируются
один раз при запуске; ``QAction`` создаётся FreeCAD при вставке в меню через
``Gui.addWorkbenchManipulator`` (С-6), поэтому манипулятор регистрируется здесь же.
"""

from __future__ import annotations

from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

from ..adapters.base import STANDARD_OPERATIONS
from ..core.frame import Alignment
from ..core.i18n import tr
from ..input import operations
from ..runtime import get_runtime

ICONS = Path(__file__).resolve().parent.parent / "resources" / "icons"


def icon(name: str) -> str:
    """Путь к SVG-иконке из ресурсов."""
    return str(ICONS / f"{name}.svg")


class ToggleCommand:
    """``Axel_Toggle`` — включить или выключить манипулятор (переключатель)."""

    name = "Axel_Toggle"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP("Axel_Toggle", "Axel: manipulator"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                "Axel_Toggle", "Turn the Axel object manipulator on or off"
            ),
            "Checkable": get_runtime().enabled,
        }

    def IsActive(self) -> bool:  # noqa: D102
        return Gui.getMainWindow() is not None

    def Activated(self, index: int = 0) -> None:  # noqa: D102
        # Всегда переключаем: щелчок по действию уже перевернул галочку Qt, а Gui.runCommand
        # не трогает её и передаёт index=0. После переключения действие подгоняется под рантайм.
        runtime = get_runtime()
        runtime.toggle()
        sync_toggle_action(runtime.enabled)


ALIGN_COMMANDS: dict[str, tuple[Alignment, str, str]] = {
    "Axel_AlignWorld": (Alignment.WORLD, "Axel: world", "Manipulator axes are the global X, Y, Z"),
    "Axel_AlignWorkplane": (
        Alignment.WORKPLANE,
        "Axel: working plane",
        "Manipulator axes follow the Draft working plane (world without Draft)",
    ),
    "Axel_AlignObject": (
        Alignment.OBJECT,
        "Axel: object",
        "Manipulator axes follow the object selected last",
    ),
    "Axel_AlignView": (
        Alignment.VIEW,
        "Axel: view",
        "Manipulator axes follow the screen: X right, Y up, Z towards the viewer",
    ),
}


class AlignCommand:
    """``Axel_AlignWorld`` / ``Axel_AlignWorkplane`` / ``Axel_AlignObject`` — группа режимов."""

    def __init__(self, name: str) -> None:
        """Команда одного режима выравнивания."""
        self.name = name
        self.alignment, self.text, self.tip = ALIGN_COMMANDS[name]

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, self.text),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(self.name, self.tip),
            "Checkable": False,
        }

    def IsActive(self) -> bool:  # noqa: D102
        return get_runtime().enabled

    def Activated(self, index: int = 0) -> None:  # noqa: D102
        runtime = get_runtime()
        if runtime.controller is not None:
            runtime.controller.set_alignment(self.alignment)
        sync_align_actions()


class AlignCycleCommand:
    """``Axel_AlignCycle`` — следующий режим выравнивания (F-15, аналог F4 в Rhino)."""

    name = "Axel_AlignCycle"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: next alignment"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                self.name, "Cycle alignment: world → working plane → object → view"
            ),
        }

    def IsActive(self) -> bool:  # noqa: D102
        return get_runtime().enabled

    def Activated(self) -> None:  # noqa: D102
        runtime = get_runtime()
        if runtime.controller is not None:
            alignment = runtime.controller.cycle_alignment()
            Gui.getMainWindow().statusBar().showMessage(
                tr("Axel: alignment — {}").format(tr(ALIGNMENT_TITLES[alignment])), 2000
            )
        sync_align_actions()


ALIGNMENT_TITLES = {
    Alignment.WORLD: "world",
    Alignment.WORKPLANE: "working plane",
    Alignment.OBJECT: "object",
    Alignment.VIEW: "view",
}


class RelocateCommand:
    """``Axel_Relocate`` — перенести начало манипулятора (F-17)."""

    name = "Axel_Relocate"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: relocate the origin"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                self.name, "Handles move the frame, not the object. Enter — done, Esc — cancel"
            ),
        }

    def IsActive(self) -> bool:  # noqa: D102
        runtime = get_runtime()
        return runtime.enabled and runtime.controller is not None and runtime.controller.visible

    def Activated(self) -> None:  # noqa: D102
        get_runtime().controller.start_relocate()


class ResetCommand:
    """``Axel_Reset`` — сбросить положение манипулятора (F-18)."""

    name = "Axel_Reset"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: reset the frame"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(self.name, "Default frame for the current target"),
        }

    def IsActive(self) -> bool:  # noqa: D102
        runtime = get_runtime()
        return runtime.enabled and runtime.controller is not None and runtime.controller.visible

    def Activated(self) -> None:  # noqa: D102
        get_runtime().controller.reset_frame()


class AutoResetCommand:
    """``Axel_AutoReset`` — автосброс перенесённой рамки после фиксации (F-18)."""

    name = "Axel_AutoReset"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: auto reset"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                self.name, "Return to the default frame after a drag"
            ),
            "Checkable": get_runtime().settings.auto_reset,
        }

    def IsActive(self) -> bool:  # noqa: D102
        return get_runtime().enabled

    def Activated(self, index: int = 0) -> None:  # noqa: D102
        runtime = get_runtime()
        runtime.settings.auto_reset = not runtime.settings.auto_reset
        get_runtime().save_setting("AutoReset", runtime.settings.auto_reset)
        for action in Gui.Command.get(self.name).getAction() or []:
            action.blockSignals(True)
            action.setChecked(runtime.settings.auto_reset)
            action.blockSignals(False)


class StepCommand:
    """``Axel_Step`` — шаговое перемещение и поворот (переключатель, F-22)."""

    name = "Axel_Step"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: step"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                self.name,
                "Moves snap to MoveStep, rotations to AngleStep; Ctrl inverts it",
            ),
            "Checkable": get_runtime().settings.step_enabled,
        }

    def IsActive(self) -> bool:  # noqa: D102
        return get_runtime().enabled

    def Activated(self, index: int = 0) -> None:  # noqa: D102
        runtime = get_runtime()
        enabled = not runtime.settings.step_enabled
        if runtime.controller is not None:
            runtime.controller.set_step(enabled)
        else:
            runtime.settings.step_enabled = enabled
        runtime.save_setting("StepEnabled", enabled)
        sync_step_action(enabled)


def sync_step_action(enabled: bool) -> None:
    """Согласовать галочку шага (команда и меню)."""
    cmd = Gui.Command.get(StepCommand.name)
    for action in (cmd.getAction() if cmd else None) or []:
        action.setCheckable(True)
        action.blockSignals(True)
        action.setChecked(enabled)
        action.blockSignals(False)


class OperationCommand:
    """Команда операции: двойная буква взводит операцию до перетаскивания (9.2.1, F-31).

    Пока манипулятор скрыт или операция недоступна, ``IsActive()`` ложно — сочетание в
    приложении не существует и буквы работают как без Axel. Операции адаптеров верстаков
    получают такие команды автоматически (15.1, :func:`ensure_operation_commands`).
    """

    def __init__(self, op_id: str, title: str, tip: str, key: str | None = None) -> None:
        """Команда для операции ``op_id`` с буквой ``key`` (стандартные — из таблицы 9.2.1)."""
        self.op_id = op_id
        self.name = operations.command_name(op_id)
        self.title = title
        self.tip = tip
        self.key = key or STANDARD_OPERATIONS[op_id]

    def GetResources(self) -> dict:  # noqa: D102
        resources = {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, self.title),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(self.name, self.tip),
        }
        if self.op_id not in _blocked_operations:
            resources["Accel"] = operations.accel(self.key)
        return resources

    def IsActive(self) -> bool:  # noqa: D102
        controller = get_runtime().controller
        return (
            controller is not None
            and controller.visible
            and controller.session is None
            and controller.operation(self.op_id) is not None
        )

    def Activated(self, index: int = 0) -> None:  # noqa: D102
        controller = get_runtime().controller
        if controller is not None:
            controller.arm_operation(self.op_id)


OPERATION_COMMANDS: tuple[tuple[str, str, str], ...] = (
    (
        "copy",
        "Axel: copy (C, C)",
        "The next handle drag creates a copy; C, C again clears the operation",
    ),
    (
        "extrude",
        "Axel: extrude (E, E)",
        "The next drag extrudes (adapters of stage 4)",
    ),
    (
        "split",
        "Axel: split into segments (D, D)",
        "The next drag acts as a segment-count slider (adapters of stage 4)",
    ),
)

_blocked_operations: frozenset[str] = frozenset()
_adapter_operations: dict[str, str] = {}  # операции адаптеров: id → буква (15.1)
_reload_pending = False


def operation_letters() -> dict[str, str]:
    """Все известные операции: стандартные и объявленные адаптерами, id → буква."""
    return {**STANDARD_OPERATIONS, **_adapter_operations}


def check_shortcut_conflicts() -> frozenset[str]:
    """Проверить сочетания операций при запуске и загрузке верстака (9.2.1, п. 2)."""
    global _blocked_operations
    letters = operation_letters()
    own = frozenset(operations.command_name(op) for op in letters)
    conflicts = operations.find_conflicts(letters, skip=own)
    _blocked_operations = operations.report_conflicts(conflicts)
    return _blocked_operations


def ensure_operation_commands(specs: list) -> None:
    """Создать команды для операций адаптеров, которых ещё нет (15.1, приёмка 4, п. 4).

    Вызывается контроллером при каждой пересборке цели. Стандартные буквы C, E, D закреплены
    (9.2.1): чужая операция с такой буквой или буква, занятая другой операцией, — ошибка
    регистрации, команда не создаётся. ``QAction`` новой команды появляется только после
    перестроения меню, поэтому активный верстак перезагружается отложенно.
    """
    global _reload_pending
    added = False
    for spec in specs:
        if spec.id in STANDARD_OPERATIONS or spec.id in _adapter_operations:
            continue
        letter = spec.key.upper()
        taken = {v: k for k, v in operation_letters().items()}
        if letter in taken:
            App.Console.PrintError(
                tr(
                    '[Axel] operation "{}" uses letter {}, already taken by "{}"; not registered'
                ).format(spec.id, letter, taken[letter])
                + "\n"
            )
            _adapter_operations[spec.id] = ""  # больше не пробовать
            continue
        _adapter_operations[spec.id] = letter
        command = OperationCommand(
            spec.id,
            f"Axel: {spec.title} ({letter}, {letter})",
            f"The next handle drag performs the adapter operation: {spec.title}",
            key=letter,
        )
        Gui.addCommand(command.name, command)
        added = True
    if added:
        check_shortcut_conflicts()
        if not _reload_pending:
            _reload_pending = True
            from PySide import QtCore

            QtCore.QTimer.singleShot(0, _reload_workbench)
    sync_operation_actions()


def sync_operation_actions() -> None:
    """Подогнать доступность действий операций под ``IsActive()``.

    FreeCAD пересчитывает активность команд по смене выделения и документа, а выбор точки
    редактирования (7.10) для него невидим — иначе E, E для вершины включится с опозданием.
    """
    for op_id in operation_letters():
        command = Gui.Command.get(operations.command_name(op_id))
        if command is None:
            continue
        active = command.isActive()
        for action in command.getAction() or []:
            if action.isEnabled() != active:
                action.setEnabled(active)


def _reload_workbench() -> None:
    """Перестроить меню активного верстака, чтобы новые команды получили ``QAction``."""
    global _reload_pending
    _reload_pending = False
    try:
        Gui.activeWorkbench().reloadActive()
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(f"[Axel] reloadActive failed: {exc!r}\n")


def adapter_operation_commands() -> list[str]:
    """Имена команд операций адаптеров, у которых есть буква."""
    return [operations.command_name(op) for op, letter in _adapter_operations.items() if letter]


class SettingsCommand:
    """``Axel_Settings`` — открыть страницу настроек (15.1)."""

    name = "Axel_Settings"

    def GetResources(self) -> dict:  # noqa: D102
        return {
            "Pixmap": icon("Axel"),
            "MenuText": App.Qt.QT_TRANSLATE_NOOP(self.name, "Axel: settings…"),
            "ToolTip": App.Qt.QT_TRANSLATE_NOOP(
                self.name, "Open the Axel settings page in the FreeCAD dialog"
            ),
        }

    def IsActive(self) -> bool:  # noqa: D102
        return Gui.getMainWindow() is not None

    def Activated(self) -> None:  # noqa: D102
        from . import preferences

        preferences.show_page()


MENU_COMMANDS = (
    ToggleCommand.name,
    *ALIGN_COMMANDS.keys(),
    AlignCycleCommand.name,
    RelocateCommand.name,
    ResetCommand.name,
    StepCommand.name,
    AutoResetCommand.name,
    SettingsCommand.name,
    *(operations.COMMAND_NAMES[op] for op, _, _ in OPERATION_COMMANDS),
)


class MenuManipulator:
    """Встраивает команды Axel в меню «Вид» и панель «View» всех верстаков (13.1, п. 2)."""

    def modifyMenuBar(self) -> list[dict]:  # noqa: D102
        names = (*MENU_COMMANDS, *adapter_operation_commands())
        return [{"append": name, "menuItem": "Std_ViewFitAll"} for name in names]

    def modifyToolBars(self) -> list[dict]:  # noqa: D102
        return [{"append": ToggleCommand.name, "toolBar": "View"}]


def sync_align_actions() -> None:
    """Отметить действие текущего режима выравнивания (группа переключателей)."""
    runtime = get_runtime()
    current = runtime.controller.alignment if runtime.controller else None
    for name, (alignment, _, _) in ALIGN_COMMANDS.items():
        cmd = Gui.Command.get(name)
        for action in (cmd.getAction() if cmd else None) or []:
            action.setCheckable(True)
            action.blockSignals(True)
            action.setChecked(alignment is current)
            action.blockSignals(False)


_manipulator: MenuManipulator | None = None
_registered = False


def register_commands() -> None:
    """Зарегистрировать команды и манипулятор меню; повторный вызов безопасен."""
    global _manipulator, _registered
    if _registered:
        return
    Gui.addCommand(ToggleCommand.name, ToggleCommand())
    for name in ALIGN_COMMANDS:
        Gui.addCommand(name, AlignCommand(name))
    Gui.addCommand(AlignCycleCommand.name, AlignCycleCommand())
    for cls in (RelocateCommand, ResetCommand, AutoResetCommand, StepCommand, SettingsCommand):
        Gui.addCommand(cls.name, cls())
    check_shortcut_conflicts()
    for op_id, title, tip in OPERATION_COMMANDS:
        command = OperationCommand(op_id, title, tip)
        Gui.addCommand(command.name, command)
    _manipulator = MenuManipulator()
    Gui.addWorkbenchManipulator(_manipulator)
    get_runtime().add_listener(sync_toggle_action)
    # QAction создаётся при активации верстака — тогда же подогнать галочку под состояние
    Gui.getMainWindow().workbenchActivated.connect(_sync_all)
    _registered = True


def _sync_all(_name: str = "") -> None:
    sync_toggle_action(get_runtime().enabled)
    sync_align_actions()
    sync_step_action(get_runtime().settings.step_enabled)
    check_shortcut_conflicts()  # клавиши могли измениться вместе с верстаком (9.2.1)


def sync_toggle_action(enabled: bool) -> None:
    """Согласовать галочку команды с состоянием (кнопка строки состояния, программное включение)."""
    cmd = Gui.Command.get(ToggleCommand.name)
    if cmd is None:
        return
    for action in cmd.getAction() or []:
        if action.isChecked() != enabled:
            action.blockSignals(True)  # иначе toggled → Activated → повторное переключение
            action.setChecked(enabled)
            action.blockSignals(False)
