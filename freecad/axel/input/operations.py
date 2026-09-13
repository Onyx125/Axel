"""Операции двойными буквами: команды FreeCAD и проверка конфликтов (9.2.1, F-31).

Сочетание живёт в обычной команде FreeCAD с ``GetResources()["Accel"] = "C, C"``. ``QAction``
создаётся только после вставки команды в меню, поэтому команды операций встраиваются через
``Gui.addWorkbenchManipulator`` (13.1). Пока манипулятор скрыт или операция недоступна,
``IsActive()`` ложно и клавиша доходит до 3D-вида — сочетаний Axel в приложении нет (9.2.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as App
import FreeCADGui as Gui

from ..adapters.base import STANDARD_OPERATIONS
from ..core.i18n import tr

STANDARD_TITLES: dict[str, str] = {
    "copy": "copy",
    "extrude": "extrude",
    "split": "split into segments",
}

COMMAND_NAMES: dict[str, str] = {
    "copy": "Axel_OpCopy",
    "extrude": "Axel_OpExtrude",
    "split": "Axel_OpSplit",
}
"""Команды стандартных операций (15.1); операции адаптеров получают имя ``command_name``."""


def command_name(op_id: str) -> str:
    """Имя команды FreeCAD для операции: стандартное или ``Axel_Op_<id>`` (15.1)."""
    if op_id in COMMAND_NAMES:
        return COMMAND_NAMES[op_id]
    safe = "".join(ch if ch.isalnum() else "_" for ch in op_id)
    return f"Axel_Op_{safe}"


def accel(letter: str) -> str:
    """Буква операции → сочетание FreeCAD: ``C`` → ``C, C``."""
    return f"{letter.upper()}, {letter.upper()}"


@dataclass(frozen=True)
class Conflict:
    """Совпадение сочетания операции с чужой командой (9.2.1, п. 2)."""

    op_id: str
    accel: str
    command: str  # имя мешающей команды FreeCAD
    exact: bool  # True — точное совпадение (сочетание не занимаем), False — предупреждение

    @property
    def message(self) -> str:
        """Строка для отчёта."""
        if self.exact:
            title = tr(STANDARD_TITLES.get(self.op_id, self.op_id))
            return (
                tr(
                    'Axel: shortcut "{}" is taken by command {} — operation "{}" gets no keys. '
                    "Reassign it in Tools → Customize"
                ).format(self.accel, self.command, title)
                + "\n"
            )
        return (
            tr(
                'Axel: command {} uses key "{}" — it will fire after ShortcutTimeout, '
                'while "{}" fires at once'
            ).format(self.command, self.accel[0], self.accel)
            + "\n"
        )


def _shortcut_of(command: object) -> str:
    """Сочетание команды или пустая строка: у команды без действия ``getShortcut`` бросает."""
    try:
        return command.getShortcut() or ""
    except Exception:  # noqa: BLE001 — команда без действия
        return ""


def shortcuts_in_use() -> dict[str, list[str]]:
    """Сочетания всех команд FreeCAD: сочетание (в верхнем регистре) → имена команд."""
    used: dict[str, list[str]] = {}
    for name in Gui.listCommands():
        command = Gui.Command.get(name)
        if command is None:
            continue
        shortcut = _shortcut_of(command)
        if shortcut:
            used.setdefault(shortcut.upper().replace(" ", ""), []).append(name)
    return used


def find_conflicts(letters: dict[str, str], skip: frozenset[str] = frozenset()) -> list[Conflict]:
    """Конфликты сочетаний операций ``{op_id: буква}`` с командами FreeCAD (9.2.1, п. 2).

    Точное совпадение полного сочетания — операция клавиши не занимает. Совпадение с
    одиночной первой буквой — только предупреждение: ``ShortcutManager`` выбирает самое
    длинное совпадение, одиночная срабатывает по таймауту.
    """
    used = shortcuts_in_use()
    conflicts: list[Conflict] = []
    for op_id, letter in letters.items():
        combo = accel(letter)
        own = command_name(op_id)
        for command in used.get(combo.replace(" ", ""), []):
            if command == own or command in skip:
                continue
            conflicts.append(Conflict(op_id, combo, command, exact=True))
        for command in used.get(letter.upper(), []):
            if command == own or command in skip:
                continue
            conflicts.append(Conflict(op_id, combo, command, exact=False))
    return conflicts


def report_conflicts(conflicts: list[Conflict]) -> frozenset[str]:
    """Написать о конфликтах в отчёт; вернуть операции, которым сочетание не досталось."""
    blocked: set[str] = set()
    for conflict in conflicts:
        if conflict.exact:
            blocked.add(conflict.op_id)
            App.Console.PrintWarning(conflict.message)
        else:
            App.Console.PrintLog(conflict.message)
    return frozenset(blocked)


def check_standard_operations() -> frozenset[str]:
    """Проверить C, C / E, E / D, D при запуске и загрузке верстака (9.2.1, п. 2)."""
    return report_conflicts(find_conflicts(dict(STANDARD_OPERATIONS)))
