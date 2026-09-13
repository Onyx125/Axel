"""Пример адаптера простого параметрического объекта: ``Part::Cylinder`` (7.9, 17.5).

Показывает всё, что нужно адаптеру верстака:

- **масштаб** по осям рамки переводится в ``Radius`` и ``Height`` (F-05…F-07), а начало
  масштабирования учитывается сдвигом ``Placement`` — геометрия масштабируется вокруг
  начала манипулятора, как и у объектов со свободным положением;
- **выдавливание** (F-08, F-09): точка на оси цилиндра растит ``Height``, точки в плоскости
  основания — ``Radius``; «в обе стороны» растит оба конца;
- **ограничение намерения** (``constrain``): высота и радиус не меньше ``MIN_SIZE``;
- **операция-ползунок** (9.2.2): ``A, A`` — угол сектора ``Angle`` (float, 0–360°), во время
  ползунка документ не меняется, показывается маркер конца дуги;
- **подсказка рамки** (``frame_hint``): начало — центр основания.

Перемещение, поворот и копирование наследуются от ``PlacementAdapter``. Адаптер не
регистрируется автоматически: ``api.register_adapter(CylinderAdapter())``.
"""

from __future__ import annotations

import math
from dataclasses import replace as replace_intent  # для любых frozen-классов данных

import FreeCAD as App

from ..adapters.base import (
    AdapterState,
    Capabilities,
    FrameHint,
    OperationScope,
    OperationSpec,
    ParamSpec,
)
from ..adapters.placement import HANDLES as PLACEMENT_HANDLES
from ..adapters.placement import PlacementAdapter
from ..core.i18n import tr
from ..core.intent import HandleKind, Intent, Operation
from ..core.target import TargetItem

Vector = App.Vector
Placement = App.Placement

HANDLES = PLACEMENT_HANDLES | {HandleKind.SCALE_AXIS, HandleKind.EXTRUDE}
MIN_SIZE = 0.01  # мм: меньше этого высота и радиус не становятся
ANGLE_PARAM = ParamSpec(
    kind=float, default=360.0, minimum=0.0, maximum=360.0, title="Angle", step=5.0
)
ANGLE_OPERATION = OperationSpec(
    id="angle",
    scope=OperationScope.OBJECT,
    key="A",
    title="Sector angle",
    handles=frozenset({HandleKind.MOVE_AXIS, HandleKind.ROTATE}),
    param=ANGLE_PARAM,
)


def is_cylinder(obj: object) -> bool:
    """Объект — параметрический цилиндр Part."""
    return getattr(obj, "TypeId", "") == "Part::Cylinder"


def local_axes(item: TargetItem) -> list[Vector]:
    """Оси цилиндра (x, y, z) в глобальных координатах."""
    rotation = Placement(item.global_matrix).Rotation
    return [rotation.multVec(Vector(*unit)) for unit in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]


def local_factors(intent: Intent, item: TargetItem) -> list[float]:
    """Коэффициенты по осям цилиндра: каждой оси — коэффициент ближайшей оси рамки."""
    axes = local_axes(item)
    result = []
    for local in axes:
        best = max(range(3), key=lambda i: abs(intent.frame.axis(i).dot(local)))
        result.append(intent.factors[best])
    return result


def local_axis_of(handle_axis: int, intent: Intent, item: TargetItem) -> tuple[int, float]:
    """Ось цилиндра, ближайшая к оси ручки, и знак (ручка смотрит вдоль или против неё)."""
    direction = intent.frame.axis(handle_axis)
    axes = local_axes(item)
    index = max(range(3), key=lambda j: abs(direction.dot(axes[j])))
    return index, (1.0 if direction.dot(axes[index]) >= 0 else -1.0)


class CylinderAdapter(PlacementAdapter):
    """Масштаб, выдавливание и ползунок угла для ``Part::Cylinder``."""

    id = "example.cylinder"
    priority = 100  # адаптер верстака перекрывает стандартный ``placement`` (7.2)

    def supports(self, item: TargetItem) -> bool:
        """Цилиндры со свободным ``Placement``."""
        return is_cylinder(item.object()) and super().supports(item)

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Как у ``placement`` плюс ручки масштаба и выдавливания."""
        base = super().capabilities(item)
        return Capabilities(HANDLES, base.axes, base.can_copy, base.disabled_reason)

    def frame_hint(self, item: TargetItem) -> FrameHint:
        """Начало рамки — центр основания (12.1, п. 3)."""
        return FrameHint(origin=item.global_matrix.multVec(Vector(0, 0, 0)))

    def operations(self, item: TargetItem) -> list[OperationSpec]:
        """Ползунок угла сектора; умолчание — текущее значение ``Angle``."""
        current = float(getattr(item.object(), "Angle", 360.0))
        param = replace_intent(ANGLE_OPERATION.param, default=current)
        return [replace_intent(ANGLE_OPERATION, param=param)]

    # ------------------------------------------------------------------ сессия

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок ``Placement`` (от ``placement``) плюс ``Radius``, ``Height``, ``Angle``."""
        state = super().begin(items, intent)
        obj = items[0].object()
        state.data["radius"] = float(obj.Radius)
        state.data["height"] = float(obj.Height)
        state.data["angle"] = float(obj.Angle)
        state.recompute_preview = intent.operation in (Operation.SCALE, Operation.EXTRUDE)
        return state

    def constrain(self, state: AdapterState, intent: Intent) -> Intent:
        """Не давать высоте и радиусу стать меньше ``MIN_SIZE`` (7.9)."""
        if intent.operation is Operation.EXTRUDE and intent.handle.axis is not None:
            item = state.items[0]
            axis, sign = local_axis_of(intent.handle.axis, intent, item)
            if axis == 2:
                size, growth = state.data["height"], intent.distance * sign
                if intent.both_sides:
                    growth = 2.0 * abs(growth)
                elif growth < 0:
                    growth = -growth  # тянем за основание — высота всё равно растёт
            else:
                size, growth = state.data["radius"], intent.distance
            if size + growth < MIN_SIZE:
                return replace_intent(intent, distance=MIN_SIZE - size)
        return intent

    def preview(self, state: AdapterState, intent: Intent) -> None:
        """Применить намерение: масштаб и выдавливание — свойства, ползунок — только маркер."""
        op = intent.operation
        if op is Operation.SCALE:
            self._apply_scale(state, intent)
        elif op is Operation.EXTRUDE:
            self._apply_extrude(state, intent)
        elif op is Operation.PARAMETER:
            self._restore(state)
            state.markers = self._arc_end_marker(state, intent)
        else:
            super().preview(state, intent)

    def commit(self, state: AdapterState, intent: Intent) -> list[str]:
        """Ползунок меняет ``Angle`` только здесь (9.2.2); остальное — как предпросмотр."""
        if intent.operation is Operation.PARAMETER:
            if intent.value is not None:
                self._object(self._entries(state)[0]).Angle = float(intent.value)
            state.markers = []
            return [self._entries(state)[0].obj_name]
        return super().commit(state, intent)

    def operation_name(self, intent: Intent) -> str:
        """Название транзакции для истории отмены."""
        names = {
            Operation.SCALE: "Axel: scale cylinder",
            Operation.EXTRUDE: "Axel: extrude cylinder",
            Operation.PARAMETER: "Axel: sector angle",
        }
        return tr(names.get(intent.operation, "")) or super().operation_name(intent)

    # ------------------------------------------------------------------ вспомогательные

    def _restore(self, state: AdapterState) -> None:
        entry = self._entries(state)[0]
        obj = self._object(entry)
        obj.Placement = entry.local
        obj.Radius = state.data["radius"]
        obj.Height = state.data["height"]

    def _apply_scale(self, state: AdapterState, intent: Intent) -> None:
        entry = self._entries(state)[0]
        obj = self._object(entry)
        sx, sy, sz = local_factors(intent, entry.item)
        radial = sx if sx != 1.0 else sy  # цилиндр круглый: один радиальный коэффициент
        obj.Radius = max(MIN_SIZE, state.data["radius"] * abs(radial))
        obj.Height = max(MIN_SIZE, state.data["height"] * abs(sz))
        # масштаб относительно начала манипулятора: основание сдвигается так, чтобы
        # точка `center` осталась на месте (в локальных координатах цилиндра)
        center = intent.center if intent.center is not None else intent.frame.origin
        c = entry.item.global_matrix.inverse().multVec(center)
        shift = Vector(c.x * (1 - radial), c.y * (1 - radial), c.z * (1 - sz))
        obj.Placement = Placement(entry.local.toMatrix() * _translate(shift))

    def _apply_extrude(self, state: AdapterState, intent: Intent) -> None:
        entry = self._entries(state)[0]
        obj = self._object(entry)
        self._restore(state)
        if intent.handle.axis is None:
            return
        axis, sign = local_axis_of(intent.handle.axis, intent, entry.item)
        dist = intent.distance * sign
        if axis == 2:  # вдоль оси цилиндра — растёт высота
            if intent.both_sides:
                obj.Height = state.data["height"] + 2 * abs(dist)
                shift = Vector(0, 0, -abs(dist))
            elif dist >= 0:
                obj.Height = state.data["height"] + dist
                shift = Vector(0, 0, 0)
            else:  # тянем за основание: оно уезжает, верх стоит
                obj.Height = state.data["height"] - dist
                shift = Vector(0, 0, dist)
            obj.Placement = Placement(entry.local.toMatrix() * _translate(shift))
        else:  # в плоскости основания — радиус: от начала наружу растёт, внутрь убывает
            obj.Radius = max(MIN_SIZE, state.data["radius"] + intent.distance)

    def _arc_end_marker(self, state: AdapterState, intent: Intent) -> list[Vector]:
        if intent.value is None:
            return []
        entry = self._entries(state)[0]
        angle = math.radians(float(intent.value))
        r, h = state.data["radius"], state.data["height"]
        local = Vector(r * math.cos(angle), r * math.sin(angle), h)
        return [entry.item.global_matrix.multVec(local)]


def _translate(delta: Vector) -> App.Matrix:
    m = App.Matrix()
    m.move(delta)
    return m
