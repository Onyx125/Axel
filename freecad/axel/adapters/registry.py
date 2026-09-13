"""Реестр адаптеров и выбор адаптера для элемента цели (7.2)."""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as App

from ..core import target as axtarget
from ..core.target import Target, TargetItem
from .base import ALL_AXES, Adapter, Capabilities, OperationSpec


@dataclass
class AdapterGroup:
    """Элементы цели, обслуживаемые одним адаптером."""

    adapter: Adapter
    items: list[TargetItem]


class Registry:
    """Адаптеры по убыванию приоритета; при равном приоритете — порядок регистрации."""

    def __init__(self) -> None:
        """Пустой реестр."""
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        """Повторная регистрация с тем же ``id`` заменяет адаптер (16.2)."""
        if not adapter.id:
            raise ValueError("у адаптера должен быть непустой id")
        self._adapters[adapter.id] = adapter

    def unregister(self, adapter_id: str) -> None:
        """Снять адаптер с регистрации; неизвестный id игнорируется."""
        self._adapters.pop(adapter_id, None)

    def get(self, adapter_id: str) -> Adapter | None:
        """Адаптер по id или ``None``."""
        return self._adapters.get(adapter_id)

    def adapters(self) -> list[Adapter]:
        """Все адаптеры по убыванию приоритета."""
        return sorted(self._adapters.values(), key=lambda a: -a.priority)

    def adapter_for(self, item: TargetItem) -> Adapter | None:
        """Первый по приоритету адаптер, у которого ``supports(item)`` истинно."""
        for adapter in self.adapters():
            if adapter.supports(item):
                return adapter
        return None

    def supports_path(self, doc: App.Document, obj_path: tuple[str, ...]) -> bool:
        """Предикат для разрешения перемещаемого объекта (7.3): есть ли адаптер у пути."""
        try:
            item = TargetItem(
                doc_name=doc.Name,
                root_name=obj_path[0],
                subname="".join(n + "." for n in obj_path[1:]),
                picked_path=obj_path,
                obj_path=obj_path,
                element=None,
                global_matrix=axtarget.global_matrix_of(doc, obj_path),
            )
        except ValueError:
            return False
        return self.adapter_for(item) is not None

    def groups(self, target: Target) -> list[AdapterGroup]:
        """Элементы цели, сгруппированные по адаптерам, в порядке первого появления."""
        result: list[AdapterGroup] = []
        by_id: dict[str, AdapterGroup] = {}
        for item in target.items:
            adapter = self.adapter_for(item)
            if adapter is None:
                continue
            group = by_id.get(adapter.id)
            if group is None:
                group = AdapterGroup(adapter, [])
                by_id[adapter.id] = group
                result.append(group)
            group.items.append(item)
        return result


def combined_capabilities(groups: list[AdapterGroup]) -> Capabilities:
    """Пересечение возможностей всех групп (7.2, п. 3–4)."""
    handles: frozenset | None = None
    axes: frozenset[int] = ALL_AXES
    can_copy = True
    reason: str | None = None
    for group in groups:
        for item in group.items:
            caps = group.adapter.capabilities(item)
            handles = caps.handles if handles is None else handles & caps.handles
            axes = axes & caps.axes
            can_copy = can_copy and caps.can_copy
            if reason is None and caps.disabled_reason:
                reason = caps.disabled_reason
    return Capabilities(
        handles=handles or frozenset(), axes=axes, can_copy=can_copy, disabled_reason=reason
    )


def combined_operations(groups: list[AdapterGroup]) -> list[OperationSpec]:
    """Операции, объявленные всеми группами цели (7.2, п. 6), по первой группе."""
    if not groups:
        return []
    common: dict[str, OperationSpec] | None = None
    for group in groups:
        ids: dict[str, OperationSpec] = {}
        for item in group.items:
            for spec in group.adapter.operations(item):
                ids.setdefault(spec.id, spec)
        common = ids if common is None else {k: v for k, v in common.items() if k in ids}
    return list((common or {}).values())
