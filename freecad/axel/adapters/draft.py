"""Адаптер Draft: вершины линий как точки редактирования (7.10, F-23) и операции (7.8).

Объект целиком двигает ``PlacementAdapter`` (наследование), а выбранная вершина —
свойство ``Points`` объекта Draft Wire. ``Points`` заданы в системе координат объекта,
поэтому намерение переводится в локальные координаты матрицей ``G`` элемента цели.

Операции — эталон для адаптеров верстаков (этап 4):

- **E, E** — выдавливание концевой вершины открытой линии (область действия — точка):
  из вершины создаётся новая, она едет по ручке, линия остаётся одним Draft Wire;
  после фиксации выбранной становится новая вершина, так что E, E можно повторять.
- **D, D** — разбивка на равные сегменты (область действия — объект, ползунок 2…100):
  во время ползунка документ не меняется, будущие вершины показываются маркерами.
"""

from __future__ import annotations

from itertools import pairwise

import FreeCAD as App

from ..core import math as axmath
from ..core.i18n import tr
from ..core.intent import HandleKind, Intent, Operation, translation_matrix
from ..core.target import TargetItem
from .base import (
    AdapterState,
    Capabilities,
    EditPoint,
    FrameHint,
    OperationScope,
    OperationSpec,
    ParamSpec,
)
from .placement import PlacementAdapter

Vector = App.Vector

POINT_HANDLES = frozenset({HandleKind.MOVE_AXIS, HandleKind.MOVE_PLANE, HandleKind.MOVE_FREE})
END_POINT_HANDLES = POINT_HANDLES | {HandleKind.EXTRUDE}  # концевая вершина: шарик выдавливания
WIRE_TYPES = frozenset({"Wire"})  # операции EE и DD (7.8)
POINT_TYPES = frozenset({"Wire", "BSpline", "BezCurve"})  # вершины и масштаб через ``Points``
PARAM_SCALE: dict[str, tuple[tuple[str, int], ...]] = {
    # параметрические объекты Draft: (свойство, локальная ось, по которой он масштабируется)
    "Circle": (("Radius", 0),),
    "Polygon": (("Radius", 0),),
    "Ellipse": (("MajorRadius", 0), ("MinorRadius", 1)),
    "Rectangle": (("Length", 0), ("Height", 1)),
}
MIN_SIZE = 0.001  # мм: параметр не может стать нулём или отрицательным

EXTRUDE_TITLE = "Extrude vertex"
SPLIT_PARAM = ParamSpec(kind=int, default=2, minimum=2, maximum=100, title="Segments")
SPLIT_OPERATION = OperationSpec(
    id="split",
    scope=OperationScope.OBJECT,
    key="D",
    title="Split into segments",
    handles=frozenset({HandleKind.MOVE_AXIS}),
    param=SPLIT_PARAM,
)


def draft_type(obj: object) -> str | None:
    """Тип объекта Draft (``obj.Proxy.Type``) или ``None``."""
    proxy = getattr(obj, "Proxy", None)
    return getattr(proxy, "Type", None) if proxy is not None else None


def is_wire(obj: object) -> bool:
    """Объект — Draft Wire (в том числе Draft Line): вершины, операции EE и DD."""
    return draft_type(obj) in WIRE_TYPES and hasattr(obj, "Points")


def has_points(obj: object) -> bool:
    """Объект Draft, заданный точками ``Points``: Wire, BSpline, BezCurve."""
    return draft_type(obj) in POINT_TYPES and hasattr(obj, "Points")


def is_parametric(obj: object) -> bool:
    """Параметрический объект Draft, масштабируемый через свойства (``PARAM_SCALE``)."""
    kind = draft_type(obj)
    return kind in PARAM_SCALE and all(hasattr(obj, prop) for prop, _ in PARAM_SCALE[kind])


def local_factors(intent: Intent, item: TargetItem) -> list[float]:
    """Коэффициенты по локальным осям объекта: каждой — коэффициент ближайшей оси рамки."""
    rotation = App.Placement(item.global_matrix).Rotation
    result = []
    for unit in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        local = rotation.multVec(Vector(*unit))
        best = max(range(3), key=lambda i: abs(intent.frame.axis(i).dot(local)))
        result.append(intent.factors[best])
    return result


def is_closed(obj: object) -> bool:
    """Линия замкнута (свойство ``Closed``)."""
    return bool(getattr(obj, "Closed", False))


def wire_rotation(points: list[Vector], z_ref: Vector) -> App.Rotation | None:
    """Ориентация «по объекту» для линии, как у Gumball Rhino (12.2, замечание пользователя).

    X — вдоль первого ненулевого сегмента, Z — нормаль плоскости линии (первая тройка
    неколлинеарных точек), для отрезка и коллинеарных точек — ``z_ref`` (ось Z ``Placement``
    объекта, обычно нормаль рабочей плоскости при создании), спроецированная на плоскость,
    перпендикулярную X; знак Z — как у ``z_ref``. Y = Z × X. ``None`` — направления нет
    (меньше двух различных точек).
    """
    eps = 1e-9
    x = None
    for a, b in pairwise(points):
        d = b - a
        if d.Length > eps:
            x = d.normalize()
            break
    if x is None:
        return None
    normal = None
    p0 = points[0]
    for p in points[1:]:
        n = x.cross(p - p0)
        if n.Length > eps:
            normal = n.normalize()
            break
    if normal is None:
        normal = z_ref - x * z_ref.dot(x)
        if normal.Length < eps:  # линия вдоль z_ref: любая перпендикулярная ось
            normal = x.cross(Vector(0, 1, 0) if abs(x.y) < 0.9 else Vector(1, 0, 0))
        normal.normalize()
    elif normal.dot(z_ref) < 0:
        normal = -normal
    y = normal.cross(x)
    matrix = App.Matrix()
    matrix.A11, matrix.A21, matrix.A31 = x.x, x.y, x.z
    matrix.A12, matrix.A22, matrix.A32 = y.x, y.y, y.z
    matrix.A13, matrix.A23, matrix.A33 = normal.x, normal.y, normal.z
    return App.Placement(matrix).Rotation


def split_points(points: list[Vector], segments: int, closed: bool) -> list[Vector]:
    """Точки линии после разбивки каждого ребра на ``segments`` равных частей (7.8)."""
    if segments < 2 or len(points) < 2:
        return [Vector(p) for p in points]
    edges = list(pairwise(points))
    if closed:
        edges.append((points[-1], points[0]))
    result: list[Vector] = []
    for a, b in edges:
        for k in range(segments):
            result.append(a + (b - a) * (k / segments))
    if not closed:
        result.append(Vector(points[-1]))
    return result


def inserted_points(points: list[Vector], segments: int, closed: bool) -> list[Vector]:
    """Только новые вершины разбивки — для маркеров результата (8.4)."""
    if segments < 2 or len(points) < 2:
        return []
    edges = list(pairwise(points))
    if closed:
        edges.append((points[-1], points[0]))
    return [a + (b - a) * (k / segments) for a, b in edges for k in range(1, segments)]


class DraftAdapter(PlacementAdapter):
    """Объекты Draft: вершины и операции Wire, масштаб; объект целиком — как у ``placement``.

    Масштаб (7.8): у объектов с ``Points`` (Wire, BSpline, BezCurve) точки преобразуются
    матрицей намерения точно, в любой рамке; у параметрических (Circle, Polygon, Ellipse,
    Rectangle) масштабируются свойства по ближайшим к осям рамки локальным осям, а
    ``Placement`` сдвигается так, чтобы центр масштаба остался на месте.
    """

    id = "axel.draft"
    priority = 100  # адаптер верстака (7.2)

    def supports(self, item: TargetItem) -> bool:
        """Объекты Draft с точками и параметрические (``PARAM_SCALE``)."""
        obj = item.object()
        return has_points(obj) or is_parametric(obj)

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Как у ``placement`` плюс ручки масштаба и выдавливания (7.8)."""
        base = super().capabilities(item)
        return Capabilities(
            base.handles | {HandleKind.SCALE_AXIS, HandleKind.EXTRUDE},
            base.axes,
            base.can_copy,
            base.disabled_reason,
        )

    def frame_hint(self, item: TargetItem) -> FrameHint | None:
        """Ориентация «по объекту»: X вдоль линии, Z — нормаль её плоскости (12.2)."""
        obj = item.object()
        if not has_points(obj) or len(obj.Points) < 2:
            return None
        matrix = item.global_matrix
        points = [matrix.multVec(p) for p in obj.Points]
        z_ref = App.Placement(matrix).Rotation.multVec(Vector(0, 0, 1))
        rotation = wire_rotation(points, z_ref)
        return FrameHint(rotation=rotation) if rotation is not None else None

    def edit_points(self, item: TargetItem) -> list[EditPoint]:
        """Вершины линии в мировых координатах; идентификаторы — ``v0``, ``v1``, … (7.10)."""
        obj = item.object()
        if not has_points(obj):
            return []
        matrix = item.global_matrix
        count = len(obj.Points)
        ends = {0, count - 1} if is_wire(obj) and not is_closed(obj) and count >= 2 else set()
        return [
            EditPoint(
                id=f"v{i}",
                position=matrix.multVec(point),
                capabilities=Capabilities(
                    handles=END_POINT_HANDLES if i in ends else POINT_HANDLES, can_copy=False
                ),
            )
            for i, point in enumerate(obj.Points)
        ]

    def operations(self, item: TargetItem) -> list[OperationSpec]:
        """D, D для объекта; E, E — только для концевых вершин открытой линии (7.8)."""
        obj = item.object()
        if not is_wire(obj):
            return []
        specs = [SPLIT_OPERATION]
        count = len(obj.Points)
        if not is_closed(obj) and count >= 2:
            specs.append(
                OperationSpec(
                    id="extrude",
                    scope=OperationScope.POINT,
                    key="E",
                    title=EXTRUDE_TITLE,
                    handles=POINT_HANDLES,
                    points=frozenset({"v0", f"v{count - 1}"}),
                )
            )
        return specs

    # ------------------------------------------------------------------ сессия

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок: для точки — её индекс и исходные ``Points``, иначе как у ``placement``.

        Выдавливание — операция EE (``op_id == "extrude"``) или шарик выдавливания на
        концевой вершине (``Operation.EXTRUDE``) — сразу вставляет копию вершины в снимок:
        дальше она двигается как обычная точка редактирования.
        """
        if intent.op_id == "split":
            return self._begin_split(items)
        if intent.point_id is None:
            state = super().begin(items, intent)
            self._snapshot_shapes(state)
            state.recompute_preview = intent.operation is Operation.SCALE  # форма меняется
            if intent.operation is Operation.EXTRUDE:
                self._begin_extrude(state)
            return state
        item = items[0]
        obj = item.object()
        state = AdapterState(list(items))
        index = int(intent.point_id[1:])
        points = [Vector(p) for p in obj.Points]
        if intent.op_id == "extrude" or intent.operation is Operation.EXTRUDE:
            if is_closed(obj) or index not in (0, len(points) - 1):
                raise ValueError("extrude: only an end vertex of an open line can be extruded")
            if index == 0:
                points.insert(0, Vector(points[0]))  # новая вершина встаёт в начало
            else:
                points.append(Vector(points[-1]))
                index = len(points) - 1
            state.select_point = f"v{index}"  # после фиксации выбрана новая вершина
        state.data["point_index"] = index
        state.data["points"] = points
        state.data["obj_name"] = obj.Name
        state.recompute_preview = True  # вершина видна на месте только после пересчёта
        # намерение задано в мировых координатах, Points — в координатах объекта
        state.data["inverse"] = item.global_matrix.inverse()
        return state

    def _begin_split(self, items: list[TargetItem]) -> AdapterState:
        item = items[0]
        obj = item.object()
        state = AdapterState(list(items))
        state.data["points"] = [Vector(p) for p in obj.Points]
        state.data["closed"] = is_closed(obj)
        state.data["obj_name"] = obj.Name
        return state

    def preview(self, state: AdapterState, intent: Intent) -> None:
        """Сдвинуть выбранную вершину; для ползунка — только маркеры, документ не трогается."""
        if intent.operation is Operation.PARAMETER:
            self._preview_split(state, intent)
            return
        if intent.point_id is None:
            if intent.operation is Operation.SCALE:
                self._apply_scale(state, intent)
            elif intent.operation is Operation.EXTRUDE:
                self._apply_extrude(state, intent)
            else:
                super().preview(state, intent)
            return
        obj = state.items[0].object()
        original = state.data["points"]
        index = state.data["point_index"]
        points = [Vector(p) for p in original]
        matrix = state.items[0].global_matrix
        world = matrix.multVec(original[index])
        if intent.operation is Operation.EXTRUDE:  # шарик: вдоль оси на расстояние (10.7)
            moved_world = world + (intent.axis or Vector()) * intent.distance
        else:
            moved_world = intent.matrix().multVec(world)
        points[index] = state.data["inverse"].multVec(moved_world)
        obj.Points = points

    def _preview_split(self, state: AdapterState, intent: Intent) -> None:
        if intent.value is None:
            state.markers = []
            return
        matrix = state.items[0].global_matrix
        new_points = inserted_points(state.data["points"], int(intent.value), state.data["closed"])
        state.markers = [matrix.multVec(p) for p in new_points]

    def commit(self, state: AdapterState, intent: Intent) -> list[str]:
        """Окончательно применить; вернуть имена изменённых объектов."""
        if intent.operation is Operation.PARAMETER:
            state.markers = []
            if intent.value is None:
                return []
            obj = state.items[0].object()
            obj.Points = split_points(state.data["points"], int(intent.value), state.data["closed"])
            return [state.data["obj_name"]]
        if intent.point_id is None:
            changed = super().commit(state, intent)
            if intent.operation is Operation.EXTRUDE:
                changed = changed + list(state.data["extrusions"].values())
                state.select_objects = list(state.data["extrusions"].values())
            return changed
        self.preview(state, intent)
        return [state.data["obj_name"]]

    def duplicate(self, state: AdapterState) -> AdapterState:
        """Копии (11.5) получают те же снимки формы, что и оригиналы."""
        new_state = super().duplicate(state)
        for old, new in zip(self._entries(state), self._entries(new_state), strict=True):
            for key in ("scale_points", "scale_params"):
                if old.obj_name in state.data.get(key, {}):
                    new_state.data.setdefault(key, {})[new.obj_name] = state.data[key][old.obj_name]
        return new_state

    def operation_name(self, intent: Intent) -> str:
        """Название для истории отмены."""
        if intent.op_id == "split":
            return tr("Axel: split into segments")
        if intent.op_id == "extrude" or (
            intent.point_id is not None and intent.operation is Operation.EXTRUDE
        ):
            return tr("Axel: extrude vertex")
        if intent.point_id is not None:
            return tr("Axel: vertex")
        if intent.operation is Operation.SCALE:
            return tr("Axel: scale")
        if intent.operation is Operation.EXTRUDE:
            return tr("Axel: extrude")
        return super().operation_name(intent)

    # ------------------------------------------------------------------ выдавливание (7.8)

    def _begin_extrude(self, state: AdapterState) -> None:
        """На каждый объект — ``Part::Extrusion`` от него; база прячется, как у Part Extrude.

        Объекты создаются внутри транзакции сессии: отмена (Esc, щелчок без сдвига) откатывает
        и их, и видимость базы.
        """
        extrusions: dict[str, str] = {}
        for entry in self._entries(state):
            obj = self._object(entry)
            ext = obj.Document.addObject("Part::Extrusion", "Extrude")
            ext.Label = tr("Extrude {}").format(obj.Label)
            ext.Base = obj
            ext.DirMode = "Custom"
            ext.Dir = Vector(0, 0, 1)
            ext.LengthFwd = 0.0
            ext.Solid = False
            container = obj.getParentGeoFeatureGroup()
            if container is not None:
                container.addObject(ext)
            obj.Visibility = False
            extrusions[entry.obj_name] = ext.Name
        state.data["extrusions"] = extrusions
        state.created_objects = list(extrusions.values())
        state.recompute_preview = True

    def _apply_extrude(self, state: AdapterState, intent: Intent) -> None:
        """Направление — ось ручки (глобальная, как ``Dir``), длина со знаком, симметрия."""
        if intent.axis is None:
            return
        for entry in self._entries(state):
            ext = entry.item.document().getObject(state.data["extrusions"][entry.obj_name])
            if ext is None:
                continue
            ext.Dir = Vector(intent.axis)
            ext.LengthFwd = float(intent.distance)
            ext.Symmetric = bool(intent.both_sides)

    # ------------------------------------------------------------------ масштаб (7.8)

    def _snapshot_shapes(self, state: AdapterState) -> None:
        """Исходная форма каждого объекта: точки или масштабируемые свойства."""
        points: dict[str, list[Vector]] = {}
        params: dict[str, dict[str, float]] = {}
        for entry in self._entries(state):
            obj = self._object(entry)
            if has_points(obj):
                points[entry.obj_name] = [Vector(p) for p in obj.Points]
            elif is_parametric(obj):
                params[entry.obj_name] = {
                    prop: float(getattr(obj, prop)) for prop, _ in PARAM_SCALE[draft_type(obj)]
                }
        state.data["scale_points"] = points
        state.data["scale_params"] = params

    def _apply_scale(self, state: AdapterState, intent: Intent) -> None:
        """Масштаб от снимка: точки — матрицей ``D``, свойства — по локальным осям."""
        delta = intent.matrix()
        for entry in self._entries(state):
            obj = self._object(entry)
            matrix = entry.item.global_matrix
            if entry.obj_name in state.data["scale_points"]:
                inverse = matrix.inverse()
                obj.Points = [
                    inverse.multVec(delta.multVec(matrix.multVec(p)))
                    for p in state.data["scale_points"][entry.obj_name]
                ]
                obj.Placement = entry.local
            elif entry.obj_name in state.data["scale_params"]:
                factors = local_factors(intent, entry.item)
                for prop, axis in PARAM_SCALE[draft_type(obj)]:
                    value = state.data["scale_params"][entry.obj_name][prop]
                    setattr(obj, prop, max(MIN_SIZE, value * abs(factors[axis])))
                # центр масштаба остаётся на месте: начало объекта переносится матрицей D
                base = matrix.multVec(Vector(0, 0, 0))
                shift = translation_matrix(delta.multVec(base) - base)
                obj.Placement = axmath.local_after_global(entry.parent, shift, entry.local)
