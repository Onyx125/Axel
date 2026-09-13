"""Стандартный адаптер ``attachment`` (7.6): присоединённые объекты через ``AttachmentOffset``.

Глобальное положение ``G = P·A·O``, где ``A`` — положение, вычисленное присоединением,
``O`` — ``AttachmentOffset``. Отсюда ``O' = (P·A)⁻¹·D·(P·A)·O``; ``P·A = G·O⁻¹`` берётся из
глобального положения по пути, поэтому присоединение к чему угодно (грань, ребро, LCS)
обрабатывается одинаково.

Предпросмотр: ``Placement`` присоединённого объекта пересчитывается только при пересчёте
документа, поэтому во время перетаскивания адаптер пишет и ``AttachmentOffset``, и
вычисленный ``Placement`` — иначе объект не двигался бы на экране (11.2, ``Never``).
"""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as App

from ..core import math as axmath
from ..core.i18n import tr
from ..core.intent import Intent
from ..core.target import TargetItem
from .base import Adapter, AdapterState, Capabilities
from .placement import HANDLES, OPERATION_NAMES, is_attached, placement_bound_by_expression

Placement = App.Placement
Matrix = App.Matrix


def offset_bound_by_expression(obj: App.DocumentObject) -> bool:
    """``AttachmentOffset`` целиком или его компонент задан выражением."""
    return any(
        path.lstrip(".").split(".")[0] == "AttachmentOffset" for path, _ in obj.ExpressionEngine
    )


@dataclass
class _Entry:
    item: TargetItem
    obj_name: str
    offset: Placement  # O
    parent: Matrix  # P·A = G·O⁻¹
    placement: Placement  # исходный Placement для возврата при единичном намерении


class AttachmentAdapter(Adapter):
    """Перемещение и поворот присоединённого объекта через ``AttachmentOffset``."""

    id = "axel.attachment"
    priority = 10

    def supports(self, item: TargetItem) -> bool:
        """Объект с расширением присоединения и режимом, отличным от «отключено»."""
        obj = item.object()
        return obj is not None and "AttachmentOffset" in obj.PropertiesList and is_attached(obj)

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Те же ручки, что у ``placement``; причина недоступности — выражение или запрет."""
        obj = item.object()
        reason = None
        if offset_bound_by_expression(obj) or placement_bound_by_expression(obj):
            reason = tr("Attachment offset is driven by an expression")
        elif "ReadOnly" in obj.getPropertyStatus("AttachmentOffset"):
            reason = tr("Attachment offset is read-only")
        return Capabilities(handles=HANDLES, can_copy=False, disabled_reason=reason)

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок: ``O`` и ``P·A = G·O⁻¹`` для каждого элемента."""
        entries = []
        for item in items:
            obj = item.object()
            offset = Placement(obj.AttachmentOffset)
            parent = axmath.parent_matrix(Placement(item.global_matrix), offset)
            entries.append(_Entry(item, obj.Name, offset, parent, Placement(obj.Placement)))
        state = AdapterState(list(items))
        state.data["entries"] = entries
        return state

    def preview(self, state: AdapterState, intent: Intent) -> None:
        """``O' = (P·A)⁻¹·D·(P·A)·O`` и предварительный ``Placement = P·A·O'``."""
        if intent.is_identity():
            for entry in self._entries(state):
                obj = self._object(entry)
                obj.AttachmentOffset = entry.offset
                obj.Placement = entry.placement
            return
        delta = intent.matrix()
        for entry in self._entries(state):
            obj = self._object(entry)
            new_offset = axmath.local_after_global(entry.parent, delta, entry.offset)
            obj.AttachmentOffset = new_offset
            obj.Placement = Placement(entry.parent * new_offset.toMatrix())

    def commit(self, state: AdapterState, intent: Intent) -> list[str]:
        """Окончательно применить; пересчёт документа восстановит ``Placement`` из привязки."""
        self.preview(state, intent)
        return [entry.obj_name for entry in self._entries(state)]

    def operation_name(self, intent: Intent) -> str:
        """Название для истории отмены."""
        return OPERATION_NAMES.get(intent.operation, "Axel")

    @staticmethod
    def _entries(state: AdapterState) -> list[_Entry]:
        return state.data["entries"]  # type: ignore[return-value]

    @staticmethod
    def _object(entry: _Entry) -> App.DocumentObject:
        obj = entry.item.document().getObject(entry.obj_name)
        if obj is None:
            raise RuntimeError(f"объект {entry.obj_name!r} удалён во время сессии")
        return obj
