"""Публичный API Axel для верстаков (раздел 16 спецификации), версия ``API_VERSION = 1``.

Единственная точка, из которой другие дополнения импортируют Axel. Реэкспорт классов данных,
базового класса адаптера, функций регистрации, событий, правил подавления и доступа к
текущей цели. Модуль импортируется без интерфейса: функции, которым нужен запущенный
манипулятор, отвечают «выключен» / ``None``, если рантайм не поднят.

Пример адаптера — ``freecad.axel.examples.cylinder``; руководство —
``docs/Руководство автора адаптера.md``.
"""

from __future__ import annotations

from collections.abc import Callable

from . import API_VERSION
from .adapters.base import (
    STANDARD_OPERATIONS,
    Adapter,
    AdapterState,
    Capabilities,
    EditPoint,
    FrameHint,
    OperationScope,
    OperationSpec,
    ParamSpec,
)
from .adapters.registry import Registry
from .core.events import events, suppression
from .core.frame import Alignment, Frame
from .core.intent import HandleId, HandleKind, Intent, Operation, Source
from .core.target import Target, TargetItem

__all__ = [
    "API_VERSION",
    "STANDARD_OPERATIONS",
    "Adapter",
    "AdapterState",
    "Alignment",
    "Capabilities",
    "EditPoint",
    "Frame",
    "FrameHint",
    "HandleId",
    "HandleKind",
    "Intent",
    "Operation",
    "OperationScope",
    "OperationSpec",
    "ParamSpec",
    "Source",
    "Target",
    "TargetItem",
    "add_suppression_rule",
    "current_target",
    "events",
    "is_enabled",
    "refresh",
    "register_adapter",
    "registry",
    "remove_suppression_rule",
    "unregister_adapter",
]

registry = Registry()
"""Единственный реестр адаптеров приложения."""


def register_adapter(adapter: Adapter) -> None:
    """Зарегистрировать адаптер; повторная регистрация с тем же ``id`` заменяет его (16.2).

    Новый адаптер сразу учитывается для текущего выделения.
    """
    registry.register(adapter)
    refresh()


def unregister_adapter(adapter_id: str) -> None:
    """Снять адаптер с регистрации."""
    registry.unregister(adapter_id)
    refresh()


def add_suppression_rule(rule_id: str, predicate: Callable[[], bool]) -> None:
    """Скрывать манипулятор, пока ``predicate()`` истинно (13.3, Р-8)."""
    suppression.add(rule_id, predicate)


def remove_suppression_rule(rule_id: str) -> None:
    """Снять правило подавления."""
    suppression.remove(rule_id)


def _controller() -> object | None:
    try:
        from .runtime import get_runtime  # рантайму нужен FreeCADGui
    except ImportError:
        return None
    return get_runtime().controller


def is_enabled() -> bool:
    """Включён ли манипулятор."""
    try:
        from .runtime import get_runtime
    except ImportError:
        return False
    return bool(get_runtime().enabled)


def current_target() -> Target | None:
    """Текущая цель манипулятора или ``None``."""
    controller = _controller()
    return controller.target if controller is not None else None


def refresh() -> None:
    """Принудительно перестроить цель и рамку по текущему выделению."""
    controller = _controller()
    if controller is not None:
        controller.refresh()


suppression.on_change = refresh
