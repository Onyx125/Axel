"""Цель манипулятора (6.1) и разрешение перемещаемого объекта (7.3).

Цель строится по **полным путям выделения**: один объект может встречаться в сцене несколько
раз через ``App::Link``, и только путь определяет, какой экземпляр двигать. Модуль работает
с объектами документа ``FreeCAD`` и не импортирует ``FreeCADGui``: чтение выделения — тонкая
обёртка в ``view``/``gui``, сюда передаются уже пары (корень, путь).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import FreeCAD as App

Matrix = App.Matrix
DocumentObject = App.DocumentObject

ASSEMBLY_TYPES = ("Assembly::AssemblyObject",)
"""Типы сборок, для которых действует граница компонента (7.3, правило 1)."""

ASSEMBLY_LINK_TYPE = "Assembly::AssemblyLink"


def is_assembly_boundary(obj: DocumentObject) -> bool:
    """Сборка или **гибкая** подсборка: её прямые потомки — компоненты (7.3, правило 1).

    Жёсткая подсборка (``Rigid = True``) — сама компонент родительской сборки, границей не является.
    """
    if obj.TypeId in ASSEMBLY_TYPES:
        return True
    return obj.TypeId == ASSEMBLY_LINK_TYPE and not getattr(obj, "Rigid", True)


@dataclass(frozen=True)
class TargetItem:
    """Элемент цели: один путь выделения и перемещаемый объект на нём."""

    doc_name: str
    root_name: str
    subname: str  # исходный путь от корня, как в Selection: "Inner.Box2.Face3"
    picked_path: tuple[str, ...]  # имена объектов исходного пути, от корня к листу
    obj_path: tuple[str, ...]  # путь до перемещаемого объекта, префикс picked_path
    element: str | None  # "Face3", "Edge2", "Vertex1" или None
    global_matrix: Matrix  # накопленная матрица перемещаемого объекта

    @property
    def obj_name(self) -> str:
        """Имя перемещаемого объекта."""
        return self.obj_path[-1]

    @property
    def picked_name(self) -> str:
        """Имя выделенного объекта (листа пути)."""
        return self.picked_path[-1]

    @property
    def moves_other_object(self) -> bool:
        """Перемещаемый объект отличается от выделенного (7.3, обратная связь)."""
        return self.obj_path != self.picked_path

    def document(self) -> App.Document:
        """Документ элемента."""
        return App.getDocument(self.doc_name)

    def object(self) -> DocumentObject:
        """Перемещаемый объект документа."""
        return self.document().getObject(self.obj_name)

    def parent(self) -> DocumentObject | None:
        """Объект, стоящий в пути непосредственно над перемещаемым (контейнер или Link)."""
        if len(self.obj_path) < 2:
            return None
        return self.document().getObject(self.obj_path[-2])

    def obj_subname(self) -> str:
        """Путь от корня до перемещаемого объекта в формате Selection (``"Inner.Box2."``)."""
        return "".join(name + "." for name in self.obj_path[1:])


@dataclass(frozen=True)
class Target:
    """Набор элементов цели; ``active_index`` — элемент, выделенный последним."""

    items: tuple[TargetItem, ...]
    active_index: int = -1
    point_id: str | None = None  # выбранная точка редактирования (только при одном элементе)

    @property
    def active(self) -> TargetItem:
        """Активный элемент (последний выделенный)."""
        return self.items[self.active_index]

    def __len__(self) -> int:
        """Число элементов цели."""
        return len(self.items)


# ---------------------------------------------------------------------------
# Разбор путей
# ---------------------------------------------------------------------------


def split_subname(root_name: str, subname: str) -> tuple[tuple[str, ...], str | None]:
    """Разобрать путь Selection на имена объектов и подэлемент.

    ``"Inner.Box2.Face3"`` → ``(("Root", "Inner", "Box2"), "Face3")``; ``"Inner.Box2."`` и
    ``""`` дают ``element = None``. Последний сегмент без точки после него — подэлемент.
    """
    if not subname:
        return (root_name,), None
    parts = subname.split(".")
    element = parts[-1] or None
    names = tuple(p for p in parts[:-1] if p)
    return (root_name, *names), element


def global_matrix_of(doc: App.Document, obj_path: tuple[str, ...]) -> Matrix:
    """Накопленная матрица объекта по пути: ``root.getSubObject(sub, 4)``."""
    root = doc.getObject(obj_path[0])
    if root is None:
        raise ValueError(f"нет объекта {obj_path[0]!r} в документе {doc.Name!r}")
    sub = "".join(name + "." for name in obj_path[1:])
    m = root.getSubObject(sub, 4)
    if m is None:
        raise ValueError(f"путь {obj_path!r} не разрешается в документе {doc.Name!r}")
    return m


# ---------------------------------------------------------------------------
# 7.3 Какой объект перемещается
# ---------------------------------------------------------------------------

Supports = Callable[[App.Document, tuple[str, ...]], bool]
"""Предикат реестра: есть ли адаптер для объекта по пути (7.2)."""


def resolve_moving_path(
    doc: App.Document, picked_path: tuple[str, ...], supports: Supports
) -> tuple[str, ...] | None:
    """Путь до перемещаемого объекта по правилу 7.3.

    1. Если в пути есть сборка, поиск начинается с компонента ближайшей по пути сборки —
       объекты глубже никогда не перемещаются.
    2. Иначе — с листа.
    3. От начальной точки вверх до корня: первый объект, для которого есть адаптер.
    4. Если адаптера нет ни у кого — ``None`` (элемент исключается из цели).
    """
    start = len(picked_path) - 1
    for i in range(len(picked_path) - 1, -1, -1):
        obj = doc.getObject(picked_path[i])
        if obj is not None and is_assembly_boundary(obj) and i + 1 < len(picked_path):
            start = i + 1
            break
    for end in range(start, -1, -1):
        candidate = picked_path[: end + 1]
        if supports(doc, candidate):
            return candidate
    return None


def make_item(
    doc: App.Document, root_name: str, subname: str, supports: Supports
) -> TargetItem | None:
    """Построить элемент цели по паре (корень, путь) из выделения."""
    picked_path, element = split_subname(root_name, subname)
    obj_path = resolve_moving_path(doc, picked_path, supports)
    if obj_path is None:
        return None
    return TargetItem(
        doc_name=doc.Name,
        root_name=root_name,
        subname=subname,
        picked_path=picked_path,
        obj_path=obj_path,
        element=element,
        global_matrix=global_matrix_of(doc, obj_path),
    )


def make_target(
    doc: App.Document, selection: list[tuple[str, str]], supports: Supports
) -> Target | None:
    """Цель из списка пар (корень, путь) в порядке выделения; пустая цель — ``None``.

    Один и тот же перемещаемый путь встречается в цели один раз (например, две грани
    одного объекта), активным считается последний.
    """
    items: list[TargetItem] = []
    seen: dict[tuple[str, ...], int] = {}
    for root_name, subname in selection:
        item = make_item(doc, root_name, subname, supports)
        if item is None:
            continue
        if item.obj_path in seen:
            items.pop(seen[item.obj_path])
            seen = {it.obj_path: i for i, it in enumerate(items)}
        seen[item.obj_path] = len(items)
        items.append(item)
    if not items:
        return None
    return Target(tuple(items), active_index=len(items) - 1)
