"""Сессия перетаскивания (6.5, 11): одна транзакция, снимки адаптеров, предпросмотр, фиксация.

Транзакция открывается на уровне приложения (``App.setActiveTransaction``), поэтому любое
перетаскивание, включая копирование, отменяется одним Ctrl+Z (принцип 5.1.3). Сессия не
знает о мыши и виджете: контроллер передаёт ей готовые намерения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import FreeCAD as App

from ..adapters.base import AdapterState
from ..adapters.registry import AdapterGroup
from .frame import Frame
from .i18n import tr
from .intent import HandleId, Intent
from .target import Target


class SessionState(Enum):
    """Жизненный цикл сессии."""

    NEW = auto()
    OPEN = auto()
    COMMITTED = auto()
    CANCELLED = auto()


@dataclass
class GroupState:
    """Группа адаптера и её непрозрачное состояние на сессию."""

    group: AdapterGroup
    state: AdapterState


@dataclass
class DragSession:
    """Интервал от нажатия на ручку до фиксации или отмены."""

    target: Target
    handle: HandleId
    frame: Frame
    groups: list[AdapterGroup]
    grab_param: object = None  # t₀ на оси, X₀ на плоскости, угол
    last_intent: Intent | None = None
    armed_op: str | None = None  # взведённая операция на момент нажатия
    states: list[GroupState] = field(default_factory=list)
    status: SessionState = SessionState.NEW
    transaction_name: str = "Axel"

    # ------------------------------------------------------------------ 11.1
    def open(self, intent: Intent) -> None:
        """Открыть транзакцию и снять снимки всех групп.

        Копирование (``intent.copy``): после снимков вызывается ``duplicate`` каждой группы,
        и дальше сессия работает с копиями (11.5).
        """
        if self.status is not SessionState.NEW:
            raise RuntimeError(f"сессия уже {self.status.name}")
        first = self.groups[0].adapter if self.groups else None
        self.transaction_name = first.operation_name(intent) if first else "Axel"
        if intent.copy:
            self.transaction_name = tr("Axel: copy")
        App.setActiveTransaction(self.transaction_name)
        try:
            for group in self.groups:
                state = group.adapter.begin(list(group.items), intent)
                if intent.copy:
                    state = group.adapter.duplicate(state)
                self.states.append(GroupState(group, state))
        except Exception:
            App.closeActiveTransaction(True)
            self.status = SessionState.CANCELLED
            raise
        self.status = SessionState.OPEN
        self.last_intent = intent

    # ------------------------------------------------------------------ 11.2
    def constrain(self, intent: Intent) -> Intent:
        """Последовательно пропустить намерение через ``constrain`` всех групп (7.4)."""
        for gs in self.states:
            intent = gs.group.adapter.constrain(gs.state, intent)
        return intent

    def preview(self, intent: Intent) -> Intent:
        """Применить намерение ко всем группам; возвращает намерение после ``constrain``."""
        self._require_open()
        intent = self.constrain(intent)
        for gs in self.states:
            gs.group.adapter.preview(gs.state, intent)
        self.last_intent = intent
        return intent

    # ------------------------------------------------------------------ 11.3
    def commit(self, intent: Intent | None = None) -> list[str]:
        """Зафиксировать: ``commit`` всех групп, закрыть транзакцию. Возвращает имена объектов."""
        self._require_open()
        intent = self.constrain(intent if intent is not None else self.last_intent)
        changed: list[str] = []
        try:
            for gs in self.states:
                changed.extend(gs.group.adapter.commit(gs.state, intent))
        except Exception:
            self.cancel()
            raise
        App.closeActiveTransaction(False)
        self.status = SessionState.COMMITTED
        self.last_intent = intent
        return changed

    # ------------------------------------------------------------------ 11.4
    def cancel(self) -> None:
        """Откатить транзакцию (включая копии) и освободить ресурсы адаптеров."""
        if self.status is not SessionState.OPEN:
            return
        App.closeActiveTransaction(True)
        self.status = SessionState.CANCELLED
        for gs in self.states:
            try:
                gs.group.adapter.cancel(gs.state)
            except Exception as exc:  # noqa: BLE001 — освобождение не должно мешать откату
                App.Console.PrintWarning(
                    f"Axel: cancel() адаптера {gs.group.adapter.id}: {exc!r}\n"
                )

    @property
    def is_open(self) -> bool:
        """Транзакция открыта, предпросмотр допустим."""
        return self.status is SessionState.OPEN

    def markers(self) -> list[App.Vector]:
        """Маркеры результата от всех групп (ползунок, 8.4)."""
        result: list[App.Vector] = []
        for gs in self.states:
            result.extend(gs.state.markers)
        return result

    def select_point(self) -> str | None:
        """Точка, которую адаптер просит выбрать после фиксации (7.8, EE), или ``None``."""
        return next((gs.state.select_point for gs in self.states if gs.state.select_point), None)

    def select_objects(self) -> list[str]:
        """Объекты, которые адаптеры просят выделить после фиксации (например, выдавливание)."""
        names: list[str] = []
        for gs in self.states:
            names.extend(n for n in gs.state.select_objects if n not in names)
        return names

    def recompute_preview(self) -> bool:
        """Хотя бы один адаптер меняет геометрию в предпросмотре (11.2, п. 2)."""
        return any(gs.state.recompute_preview for gs in self.states)

    def changed_objects(self) -> list[str]:
        """Объекты сессии, включая созданные ею (пересчёт в предпросмотре, наблюдатель)."""
        names: list[str] = []
        for gs in self.states:
            names.extend(item.obj_name for item in gs.state.items)
            names.extend(gs.state.created_objects)
        return names

    def _require_open(self) -> None:
        if self.status is not SessionState.OPEN:
            raise RuntimeError(f"сессия не открыта ({self.status.name})")


def new_session(
    target: Target, handle: HandleId, frame: Frame, groups: list[AdapterGroup]
) -> DragSession:
    """Сессия без транзакции; открывается :meth:`DragSession.open`."""
    return DragSession(target=target, handle=handle, frame=frame, groups=groups)
