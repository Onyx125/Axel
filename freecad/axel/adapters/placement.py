"""Стандартный адаптер ``placement`` (7.5): объекты со свободным свойством ``Placement``."""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as App

from ..core import math as axmath
from ..core import target as axtarget
from ..core.i18n import tr
from ..core.intent import HandleKind, Intent, Operation
from ..core.target import TargetItem
from .base import Adapter, AdapterState, Capabilities

Placement = App.Placement
Matrix = App.Matrix

HANDLES: frozenset[HandleKind] = frozenset(
    {
        HandleKind.MOVE_AXIS,
        HandleKind.MOVE_PLANE,
        HandleKind.MOVE_FREE,
        HandleKind.ROTATE,
    }
)

OPERATION_NAMES = {
    Operation.TRANSLATE: "Axel: move",
    Operation.ROTATE: "Axel: rotate",
}


def placement_bound_by_expression(obj: App.DocumentObject) -> bool:
    """Свойство ``Placement`` целиком или его компонент задано выражением."""
    return any(path.lstrip(".").split(".")[0] == "Placement" for path, _ in obj.ExpressionEngine)


def is_attached(obj: App.DocumentObject) -> bool:
    """Объект присоединён (случай адаптера ``attachment``)."""
    return getattr(obj, "MapMode", "Deactivated") != "Deactivated"


def is_body_feature(obj: App.DocumentObject) -> bool:
    """Элемент тела PartDesign: положение определяется телом (7.5)."""
    return obj.isDerivedFrom("PartDesign::Feature") and getattr(obj, "_Body", None) is not None


def has_placement_property(obj: App.DocumentObject) -> bool:
    """У объекта есть свойство ``Placement`` типа ``App::PropertyPlacement``."""
    return (
        "Placement" in obj.PropertiesList
        and obj.getTypeIdOfProperty("Placement") == "App::PropertyPlacement"
    )


@dataclass
class _Entry:
    item: TargetItem
    obj_name: str
    local: Placement  # L — исходное локальное положение
    parent: Matrix  # P — накопленная матрица родителей, P = G·L⁻¹


class PlacementAdapter(Adapter):
    """Перемещение и поворот через свойство ``Placement``: ``L' = P⁻¹·D·P·L``."""

    id = "axel.placement"
    priority = 0

    def supports(self, item: TargetItem) -> bool:
        """Свободный ``Placement``: не присоединён, не элемент тела, не компонент сборки."""
        obj = item.object()
        if obj is None or not has_placement_property(obj):
            return False
        if is_attached(obj) or is_body_feature(obj):
            return False
        parent = item.parent()
        if parent is not None and axtarget.is_assembly_boundary(parent):
            return False  # компонент сборки — случай адаптера assembly
        return True

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Перемещение и поворот; ``disabled_reason`` при выражении или запрете редактирования."""
        obj = item.object()
        status = obj.getPropertyStatus("Placement")
        reason = None
        if placement_bound_by_expression(obj):
            reason = tr("Placement is driven by an expression")
        elif "ReadOnly" in status or "Immutable" in status:
            reason = tr("Placement is read-only")
        elif "Hidden" in status:
            reason = tr("Placement is hidden from editing")
        return Capabilities(handles=HANDLES, can_copy=True, disabled_reason=reason)

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок: для каждого элемента ``L`` и ``P = G·L⁻¹``."""
        entries = []
        for item in items:
            obj = item.object()
            local = Placement(obj.Placement)
            parent = axmath.parent_matrix(Placement(item.global_matrix), local)
            entries.append(_Entry(item, obj.Name, local, parent))
        state = AdapterState(list(items))
        state.data["entries"] = entries
        return state

    def preview(self, state: AdapterState, intent: Intent) -> None:
        """Применить полное намерение к снимку: ``L' = P⁻¹·D·P·L``."""
        if intent.is_identity():
            for entry in self._entries(state):
                self._object(entry).Placement = entry.local
            return
        delta = intent.matrix()
        for entry in self._entries(state):
            self._object(entry).Placement = axmath.local_after_global(
                entry.parent, delta, entry.local
            )

    def commit(self, state: AdapterState, intent: Intent) -> list[str]:
        """Окончательно применить; вернуть имена изменённых объектов."""
        self.preview(state, intent)
        return [entry.obj_name for entry in self._entries(state)]

    def duplicate(self, state: AdapterState) -> AdapterState:
        """Копии в контейнере оригинала; оригиналы возвращаются к ``L`` (7.5, 11.5)."""
        copies: list[_Entry] = []
        items: list[TargetItem] = []
        for entry in self._entries(state):
            obj = self._object(entry)
            doc = obj.Document
            copy = doc.copyObject(obj, False)
            container = obj.getParentGeoFeatureGroup()
            if container is not None:
                container.addObject(copy)
            obj.Placement = entry.local
            copy.Placement = entry.local
            item = _item_for_copy(entry.item, copy.Name)
            items.append(item)
            copies.append(_Entry(item, copy.Name, Placement(entry.local), entry.parent))
        new_state = AdapterState(items)
        new_state.data["entries"] = copies
        return new_state

    def operation_name(self, intent: Intent) -> str:
        """Название для истории отмены: «Axel: перемещение» или «Axel: поворот»."""
        return tr(OPERATION_NAMES.get(intent.operation, "Axel"))

    @staticmethod
    def _entries(state: AdapterState) -> list[_Entry]:
        return state.data["entries"]  # type: ignore[return-value]

    @staticmethod
    def _object(entry: _Entry) -> App.DocumentObject:
        obj = entry.item.document().getObject(entry.obj_name)
        if obj is None:
            raise RuntimeError(f"объект {entry.obj_name!r} удалён во время сессии")
        return obj


def _item_for_copy(item: TargetItem, copy_name: str) -> TargetItem:
    """Элемент цели для копии: тот же путь с заменённым последним именем."""
    obj_path = (*item.obj_path[:-1], copy_name)
    return TargetItem(
        doc_name=item.doc_name,
        root_name=obj_path[0],
        subname="".join(n + "." for n in obj_path[1:]),
        picked_path=obj_path,
        obj_path=obj_path,
        element=None,
        global_matrix=item.global_matrix,
    )
