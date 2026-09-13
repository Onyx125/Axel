"""События для верстаков (16.1) и правила подавления (16.1, 13.3) — без Qt.

Сигнал — список обработчиков. Исключение в обработчике пишется в отчёт и не прерывает
работу Axel (16.2). Все события вызываются в главном потоке из контроллера.
"""

from __future__ import annotations

from collections.abc import Callable

import FreeCAD as App


class Signal:
    """Простой сигнал: ``connect``, ``disconnect``, ``emit``."""

    def __init__(self, name: str) -> None:
        """Сигнал с именем для сообщений об ошибках."""
        self.name = name
        self._handlers: list[Callable] = []

    def connect(self, handler: Callable) -> None:
        """Подписать обработчик; повторная подписка игнорируется."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def disconnect(self, handler: Callable) -> None:
        """Отписать обработчик; неизвестный игнорируется."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def emit(self, *args: object) -> None:
        """Вызвать обработчики; ошибка одного не мешает остальным."""
        for handler in list(self._handlers):
            try:
                handler(*args)
            except Exception as exc:  # noqa: BLE001 — принцип 5.1.6
                App.Console.PrintError(f"[Axel] handler of {self.name} failed: {exc!r}\n")

    def __len__(self) -> int:
        """Число обработчиков."""
        return len(self._handlers)


class Events:
    """События публичного API (16.1)."""

    def __init__(self) -> None:
        """Пять сигналов с сигнатурами по 16.1."""
        self.drag_started = Signal("drag_started")  # (target, intent)
        self.drag_committed = Signal("drag_committed")  # (target, intent, changed_names)
        self.drag_cancelled = Signal("drag_cancelled")  # (target,)
        self.target_changed = Signal("target_changed")  # (target | None,)
        self.operation_armed = Signal("operation_armed")  # (op_id | None,)


events = Events()
"""Единственный набор событий приложения; ``api.events`` — ссылка на него."""


class SuppressionRules:
    """Правила подавления от других дополнений: манипулятор скрыт, пока хоть одно истинно."""

    def __init__(self) -> None:
        """Пусто; ``on_change`` вызывается при добавлении и удалении правила."""
        self._rules: dict[str, Callable[[], bool]] = {}
        self.on_change: Callable[[], None] | None = None

    def add(self, rule_id: str, predicate: Callable[[], bool]) -> None:
        """Добавить или заменить правило."""
        self._rules[rule_id] = predicate
        self._notify()

    def remove(self, rule_id: str) -> None:
        """Снять правило; неизвестное игнорируется."""
        if self._rules.pop(rule_id, None) is not None:
            self._notify()

    def ids(self) -> list[str]:
        """Идентификаторы правил."""
        return list(self._rules)

    def active(self) -> bool:
        """Есть ли истинное правило; ошибка предиката считается ложью и пишется в отчёт."""
        for rule_id, predicate in list(self._rules.items()):
            try:
                if predicate():
                    return True
            except Exception as exc:  # noqa: BLE001
                App.Console.PrintError(f"[Axel] suppression rule {rule_id!r} failed: {exc!r}\n")
        return False

    def _notify(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception as exc:  # noqa: BLE001
                App.Console.PrintError(f"[Axel] suppression change handler failed: {exc!r}\n")


suppression = SuppressionRules()
"""Единственный набор правил подавления приложения."""
