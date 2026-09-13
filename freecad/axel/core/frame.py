"""Рамка манипулятора (6.2): система координат манипулятора в глобальных координатах.

Правила выравнивания и начального положения (раздел 12) добавляются на этапе 2; здесь —
класс данных и простые операции над осями.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import FreeCAD as App

Vector = App.Vector
Rotation = App.Rotation


class Alignment(Enum):
    """Правило ориентации осей рамки."""

    WORLD = "world"
    WORKPLANE = "workplane"
    OBJECT = "object"
    VIEW = "view"  # X вправо по экрану, Y вверх, Z на наблюдателя (12.2)


@dataclass(frozen=True)
class Frame:
    """Начало и оси манипулятора в глобальных координатах."""

    origin: Vector
    rotation: Rotation
    alignment: Alignment = Alignment.WORLD
    relocated: bool = False

    def axis(self, index: int) -> Vector:
        """Единичная ось рамки ``index`` = 0, 1, 2 (X, Y, Z) в глобальных координатах."""
        unit = [Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1)][index]
        return self.rotation.multVec(unit)

    def plane_axes(self, normal_index: int) -> tuple[Vector, Vector]:
        """Оси плоскости, нормаль которой — ось ``normal_index`` (для Move 2D)."""
        return self.axis((normal_index + 1) % 3), self.axis((normal_index + 2) % 3)

    def moved(self, delta: Vector) -> Frame:
        """Та же рамка со сдвинутым началом."""
        return Frame(self.origin + delta, self.rotation, self.alignment, self.relocated)


def world_frame(origin: Vector) -> Frame:
    """Рамка, выровненная по миру, с началом в ``origin``."""
    return Frame(origin, Rotation(), Alignment.WORLD, False)


# ---------------------------------------------------------------------------
# 12.1–12.2 Начало и ориентация по умолчанию
# ---------------------------------------------------------------------------


class OriginMode(Enum):
    """Настройка ``OriginDefault``."""

    BOUNDING_BOX_CENTER = "BoundingBoxCenter"
    PLACEMENT_BASE = "PlacementBase"


_BBOX_CACHE: dict[tuple[str, tuple[str, ...], tuple[float, ...]], App.BoundBox | None] = {}
BBOX_CACHE_LIMIT = 256
"""Кеш габаритов: ``TopoShape.BoundBox`` в FreeCAD 1.1 оставляет по слабой ссылке на вызов,
поэтому пересчитывать габариты на каждый показ манипулятора нельзя (17.1, «память»)."""


_ORIGIN_CACHE: dict[tuple, Vector | None] = {}
"""Кеш начала рамки: ``BoundBox.Center`` и копия ``BoundBox`` тоже стоят по слабой ссылке."""


def clear_bbox_cache() -> None:
    """Сбросить кеши габаритов и начала целиком (undo/redo, смена документа)."""
    _BBOX_CACHE.clear()
    _ORIGIN_CACHE.clear()


def invalidate_bbox(obj_name: str) -> None:
    """Забыть габариты путей, в которые входит объект (изменилось свойство объекта)."""
    for key in [k for k in _BBOX_CACHE if obj_name in k[1]]:
        del _BBOX_CACHE[key]
    for key in [k for k in _ORIGIN_CACHE if any(obj_name in item[1] for item in k)]:
        del _ORIGIN_CACHE[key]


def _cache_key(item: object) -> tuple[str, tuple[str, ...], tuple[float, ...]]:
    return (item.doc_name, item.obj_path, tuple(item.global_matrix.A))


def item_bound_box(item: object) -> App.BoundBox | None:
    """Габариты перемещаемого объекта элемента цели в глобальных координатах.

    ``Part.getShape(root, sub)`` собирает форму и для контейнеров (``App::Part``), и через
    ``App::Link``; для объектов без формы — ``None``. Результат кешируется по пути и
    глобальной матрице элемента.
    """
    import Part

    key = _cache_key(item)
    if key in _BBOX_CACHE:
        return _BBOX_CACHE[key]
    doc = App.getDocument(item.doc_name)
    root = doc.getObject(item.obj_path[0])
    if root is None:
        return None
    try:
        shape = Part.getShape(root, item.obj_subname())
    except Exception:  # noqa: BLE001 — объект без формы
        return _remember(key, None)
    if shape is None or shape.isNull():
        return _remember(key, None)
    bb = shape.BoundBox
    if not bb.isValid():
        return _remember(key, None)
    return _remember(key, bb)


def _remember(
    key: tuple[str, tuple[str, ...], tuple[float, ...]], box: App.BoundBox | None
) -> App.BoundBox | None:
    """Положить габариты в кеш; при переполнении кеш сбрасывается целиком."""
    if len(_BBOX_CACHE) >= BBOX_CACHE_LIMIT:
        _BBOX_CACHE.clear()
    _BBOX_CACHE[key] = box
    return box


def target_bound_box(target: object) -> App.BoundBox | None:
    """Общие габариты цели или ``None``, если ни у одного элемента нет формы."""
    total: App.BoundBox | None = None
    for item in target.items:
        bb = item_bound_box(item)
        if bb is None:
            continue
        if total is None:
            total = App.BoundBox(bb)
        else:
            total.add(bb)
    return total


def default_origin(target: object, mode: OriginMode = OriginMode.BOUNDING_BOX_CENTER) -> Vector:
    """Начало по умолчанию (12.1, п. 4): центр габаритов или начало Placement активного."""
    if mode is OriginMode.BOUNDING_BOX_CENTER:
        key = tuple(_cache_key(item) for item in target.items)
        if key in _ORIGIN_CACHE:
            center = _ORIGIN_CACHE[key]
        else:
            bb = target_bound_box(target)
            center = Vector(bb.Center) if bb is not None else None
            if len(_ORIGIN_CACHE) >= BBOX_CACHE_LIMIT:
                _ORIGIN_CACHE.clear()
            _ORIGIN_CACHE[key] = center
        if center is not None:
            return Vector(center)
    return App.Placement(target.active.global_matrix).Base


def view_rotation(right: Vector, up: Vector) -> Rotation:
    """Поворот рамки «по виду» (12.2): X — вправо по экрану, Y — вверх, Z — на наблюдателя."""
    z = right.cross(up)
    return Rotation(right, up, z, "XYZ")


def default_frame(
    target: object,
    alignment: Alignment = Alignment.WORLD,
    origin_mode: OriginMode = OriginMode.BOUNDING_BOX_CENTER,
    workplane_rotation: Rotation | None = None,
    screen_basis: tuple[Vector, Vector] | None = None,
) -> Frame:
    """Рамка по умолчанию (12.1, 12.2).

    ``WORKPLANE`` без провайдера (``workplane_rotation is None``) и ``VIEW`` без
    ``screen_basis`` работают как ``WORLD``; ``OBJECT`` — поворот глобального положения
    активного элемента.
    """
    origin = default_origin(target, origin_mode)
    rotation = Rotation()
    if alignment is Alignment.OBJECT:
        rotation = App.Placement(target.active.global_matrix).Rotation
    elif alignment is Alignment.WORKPLANE and workplane_rotation is not None:
        rotation = workplane_rotation
    elif alignment is Alignment.VIEW and screen_basis is not None:
        rotation = view_rotation(*screen_basis)
    return Frame(origin, rotation, alignment, False)
