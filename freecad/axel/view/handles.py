"""Геометрия ручек и состояния подсветки (8.1, 8.2).

Каждая ручка — стандартный драггер Coin ``SoTranslate1Dragger`` с заменёнными частями:
от драггера берутся захват ЛКМ, кооперация со стилями навигации и обратные вызовы
(С-7), геометрия — Gumball по таблице 8.1. Собственная математика драггера не
используется: контроллер сбрасывает ``translation`` в нуль на каждом движении, поэтому
геометрия не уезжает, а намерение считается в ``core.math`` по лучу курсора.

Все размеры — в единицах «S = 1»: узел ``SoShapeScale`` (``view.screen_scale``) растягивает
единицу до ``SizePx`` логических пикселей. Размеры, заданные в пикселях (толщина линий),
задаются напрямую через ``SoDrawStyle``; размеры в пикселях у объёмных фигур делятся на ``SizePx``.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from enum import Enum, auto

from pivy import coin

from ..core import constants
from ..core.intent import HandleId, HandleKind

RGB = tuple[float, float, float]

DEFAULT_AXIS_COLORS: tuple[RGB, RGB, RGB] = (
    (0.9, 0.15, 0.15),
    (0.15, 0.7, 0.15),
    (0.15, 0.3, 0.95),
)


@dataclass(frozen=True)
class HandleStyle:
    """Размеры и цвета из настроек (15.4). Пиксели — логические."""

    size_px: float = float(constants.SIZE_PX)
    shaft_width_px: float = 1.5  # стержни стрелок и дуги; было 2,5 — тоньше по замечанию
    origin_px: float = 6.0  # было 9; на 30 % меньше по замечанию пользователя
    axis_colors: tuple[RGB, RGB, RGB] = DEFAULT_AXIS_COLORS
    hover_color: RGB = (
        0.0,
        0.0,
        0.0,
    )  # было жёлтым (1, 0.85, 0.1); чёрный по замечанию пользователя
    disabled_color: RGB = (0.55, 0.55, 0.55)
    origin_color: RGB = (1.0, 1.0, 1.0)
    outline_color: RGB = (0.2, 0.2, 0.2)
    transparency: float = 0.3  # общая прозрачность ручек (TransparencyPercent)
    plane_transparency: float = 0.5  # обводка и сетка квадрата плоскости — не меньше этого
    dimmed_transparency: float = 0.7
    disabled_transparency: float = 0.5
    hover_width_factor: float = 1.5
    show_hitboxes: bool = False  # отладка: тени ручек каркасом (параметр ShowHitboxes)

    def px(self, value_px: float) -> float:
        """Размер в пикселях → единицы ручки (S = 1)."""
        return value_px / self.size_px


class HandleState(Enum):
    """Состояние отображения ручки (8.2)."""

    NORMAL = auto()
    HOVER = auto()
    ACTIVE = auto()
    DIMMED = auto()  # остальные во время перетаскивания
    DISABLED = auto()  # disabled_reason


# Пропорции Gumball (8.1), доли от S
CONE_LEN, CONE_RADIUS = 0.208, 0.045  # длина конуса: 0,16 + 30 % в сторону начала
SHAFT_FROM, SHAFT_TO = 0.20, 1.0 - CONE_LEN  # стержень от зазора у начала до основания конуса
# кубик масштаба и шарик выдавливания — вплотную к конусу с одинаковыми зазорами
# (замечание пользователя): конус ← зазор → шарик ← зазор → кубик; ребро кубика и
# диаметр шарика равны диаметру конуса
HANDLE_GAP = 0.05
EXTRUDE_DOT_AT = SHAFT_TO - HANDLE_GAP - CONE_RADIUS  # ≈0,697·S
SCALE_BOX_AT = EXTRUDE_DOT_AT - CONE_RADIUS - HANDLE_GAP - CONE_RADIUS  # ≈0,557·S
ARC_RADIUS = constants.ARC_RADIUS_FRACTION
# дуга — четверть между −Y и −Z локальной рамки ручки: октант отрицательных осей, как в Rhino
# было 182°–268° (86°), затем 190,6°–259,4°; теперь концы считает arc_angles() от зазора SHAFT_FROM
ARC_SEGMENTS = 32
ARC_END_DOT_PX = 6.0  # диаметр шариков на концах дуги, логические пиксели
# невидимая, но пикаемая «тень» ручек (замечание пользователя: промахи): Coin рисует
# SoDrawStyle INVISIBLE, но луч-пикинг её видит — хитбокс шире видимой геометрии
# трубка вдоль стержня стрелки и дуги, ≈8 px при S = 80: радиус пикинга FreeCAD (5 px) линиям
# и так даёт ~5 px, трубка 0,07 почти ничего не добавляла (проба d19)
HIT_TUBE_RADIUS = 0.07  # было 0,10; на 30 % меньше по замечанию пользователя
# тени стрелки и дуги длиннее видимой геометрии (замечание пользователя): у стрелки —
# наружу, за вершину конуса (к началу нет — там шарик и маркеры точек); у дуги — за оба
# концевых шарика. Хвосты дуг соседних осей сходятся у отрицательной полуоси: при 10°
# зазор между трубками ≈6 px
HIT_ARROW_OVERHANG = 0.25 / 3  # было 0,25; втрое короче по замечанию пользователя
HIT_ARC_TAIL_DEG = 3.6  # хвост дуги за краем концевого шарика; было ≈7,1° (10° от центра)
# сфера вокруг кубика масштаба и шарика выдавливания, ≈5,6 px. Больше нельзя: тень объёмная,
# и в косом виде луч через точку стержня *до* кубика проходит сквозь край его тени — вдоль оси
# захват тянется на ≈1,2·r (изометрия), середина стержня уходила бы кубику (s4, d16). Шайба,
# широкая поперёк и короткая вдоль, хуже сферы: её ободок ловит луч ещё дальше от центра
HIT_DOT_RADIUS = 0.07
HIT_ARC_SEGMENTS = 8  # цилиндров вдоль дуги
ORIGIN_OUTLINE_PX = 1.25  # толщина линии контура шарика начала, px
ORIGIN_EXTRA_TRANSPARENCY = 0.2  # белый шарик прозрачнее остальных ручек на столько
ORIGIN_OUTLINE_TRANSPARENCY = 0.6  # контур прозрачнее ручек, но не менее общей прозрачности
# квадрат 0,25·S в центре габарита двух стрелок (0…1,0·S по каждой оси) — центр на 0,5·S
PLANE_FROM, PLANE_TO = 0.375, 0.625
PLANE_FILL_TRANSPARENCY = 0.75  # заливка квадрата — не меньше этого
PLANE_CORNER_FRACTION = 0.10  # радиус скругления углов квадрата в долях стороны


def node_name(handle: HandleId) -> str:
    """Имя узла по шаблону ``ax_<kind>_<axis>`` (8.3)."""
    axis = "" if handle.axis is None else f"_{handle.axis}"
    return f"ax_{handle.kind.name.lower()}{axis}"


def parse_node_name(name: str) -> HandleId | None:
    """Обратное к :func:`node_name`; ``None``, если имя не наше."""
    if not name.startswith("ax_"):
        return None
    body = name[3:]
    axis: int | None = None
    if body[-2:-1] == "_" and body[-1].isdigit():
        axis = int(body[-1])
        body = body[:-2]
    try:
        kind = HandleKind[body.upper()]
    except KeyError:
        return None
    return HandleId(kind, axis)


def axis_matrix(axis: int) -> coin.SbMatrix:
    """Поворот, переводящий локальную ось X ручки в ось рамки ``axis`` (циклическая перестановка).

    axis 0: X→X, Y→Y, Z→Z; axis 1: X→Y, Y→Z, Z→X; axis 2: X→Z, Y→X, Z→Y. Это правые тройки,
    так что геометрия, построенная вдоль локальной X, ложится на любую ось одинаково.
    """
    cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    ex, ey, ez = cols[axis % 3], cols[(axis + 1) % 3], cols[(axis + 2) % 3]
    # Coin умножает вектор-строку на матрицу (v' = v·M): строки — образы базисных векторов
    return coin.SbMatrix(
        ex[0],
        ex[1],
        ex[2],
        0,
        ey[0],
        ey[1],
        ey[2],
        0,
        ez[0],
        ez[1],
        ez[2],
        0,
        0,
        0,
        0,
        1,
    )


@dataclass
class HandleNode:
    """Узлы одной ручки и управление её состоянием."""

    id: HandleId
    root: coin.SoSwitch  # видимость (вырожденная/не поддерживается)
    dragger: coin.SoDragger
    material: coin.SoMaterial
    draw_style: coin.SoDrawStyle
    base_color: RGB
    base_width: float
    base_transparency: float = 0.0
    state: HandleState = HandleState.NORMAL
    extra_materials: list[coin.SoMaterial] = field(default_factory=list)
    # вспомогательные материалы (контуры, сетка): (материал, пол прозрачности, красить ли)
    aux_materials: list[tuple[coin.SoMaterial, float, bool]] = field(default_factory=list)
    orient: coin.SoRotation | None = None  # кольцо контура начала: поворот к камере
    geometry: coin.SoSeparator | None = None  # геометрия ручки — для показа поверх (8.2)

    @property
    def name(self) -> str:
        """Имя узла ``ax_<kind>_<axis>``."""
        return node_name(self.id)

    def set_visible(self, visible: bool) -> None:
        """Показать или скрыть ручку (переключатель ``SoSwitch``)."""
        self.root.whichChild.setValue(0 if visible else -1)

    @property
    def visible(self) -> bool:
        """Ручка показана."""
        return self.root.whichChild.getValue() == 0

    def set_state(self, state: HandleState, style: HandleStyle) -> None:
        """Применить состояние 8.2 к материалу и толщине линий."""
        self.state = state
        color, transparency, width = self.base_color, self.base_transparency, self.base_width
        if state is HandleState.HOVER:
            color, width = style.hover_color, self.base_width * style.hover_width_factor
        elif state is HandleState.ACTIVE:
            color = style.hover_color
        elif state is HandleState.DIMMED:
            transparency = max(transparency, style.dimmed_transparency)
        elif state is HandleState.DISABLED:
            color, transparency = (
                style.disabled_color,
                max(transparency, style.disabled_transparency),
            )
        for mat in (self.material, *self.extra_materials):
            mat.diffuseColor.setValue(*color)
            mat.transparency.setValue(transparency)
        for mat, floor, follow_color in self.aux_materials:
            mat.transparency.setValue(max(transparency, floor))
            if follow_color:
                mat.diffuseColor.setValue(*color)
        self.draw_style.lineWidth.setValue(width)

    def reset_dragger(self) -> None:
        """Сбросить собственный сдвиг драггера — геометрия остаётся у рамки."""
        self.dragger.translation.setValue(0, 0, 0)


# ---------------------------------------------------------------------------
# Построение геометрии
# ---------------------------------------------------------------------------


def _line_strip(points: list[tuple[float, float, float]]) -> coin.SoSeparator:
    sep = coin.SoSeparator()
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), points)
    sep.addChild(coords)
    line = coin.SoLineSet()
    line.numVertices.setValue(len(points))
    sep.addChild(line)
    return sep


def _cone_along_x(base_x: float, length: float, radius: float) -> coin.SoSeparator:
    """Конус с основанием в ``base_x`` и вершиной в ``base_x + length`` вдоль +X."""
    sep = coin.SoSeparator()
    rot = coin.SoRotationXYZ()
    rot.axis.setValue(coin.SoRotationXYZ.Z)
    rot.angle.setValue(-math.pi / 2)  # ось конуса Y → X
    sep.addChild(rot)
    tr = coin.SoTranslation()
    tr.translation.setValue(0, base_x + length / 2, 0)
    sep.addChild(tr)
    cone = coin.SoCone()
    cone.bottomRadius.setValue(radius)
    cone.height.setValue(length)
    sep.addChild(cone)
    return sep


def _sphere_at(x: float, radius: float) -> coin.SoSeparator:
    return _sphere_at_point((x, 0.0, 0.0), radius)


def _sphere_at_point(point: tuple[float, float, float], radius: float) -> coin.SoSeparator:
    sep = coin.SoSeparator()
    tr = coin.SoTranslation()
    tr.translation.setValue(*point)
    sep.addChild(tr)
    sphere = coin.SoSphere()
    sphere.radius.setValue(radius)
    sep.addChild(sphere)
    return sep


def _circle_xy(radius: float, segments: int = 48) -> coin.SoSeparator:
    """Окружность в плоскости XY (нормаль Z — к камере после поворота)."""
    pts = [
        (
            radius * math.cos(2 * math.pi * i / segments),
            radius * math.sin(2 * math.pi * i / segments),
            0.0,
        )
        for i in range(segments + 1)
    ]
    return _line_strip(pts)


def _arc_end(radius: float, deg: float) -> tuple[float, float, float]:
    """Точка дуги ``_arc_yz`` на угле ``deg``."""
    a = math.radians(deg)
    return (0.0, radius * math.cos(a), radius * math.sin(a))


def _cube_at(x: float, edge: float) -> coin.SoSeparator:
    sep = coin.SoSeparator()
    tr = coin.SoTranslation()
    tr.translation.setValue(x, 0, 0)
    sep.addChild(tr)
    cube = coin.SoCube()
    cube.width.setValue(edge)
    cube.height.setValue(edge)
    cube.depth.setValue(edge)
    sep.addChild(cube)
    return sep


def _arc_yz(radius: float, from_deg: float, to_deg: float, segments: int) -> coin.SoSeparator:
    """Дуга в плоскости YZ (перпендикулярно локальной X) от ``from_deg`` до ``to_deg``."""
    pts = []
    for i in range(segments + 1):
        a = math.radians(from_deg + (to_deg - from_deg) * i / segments)
        pts.append((0.0, radius * math.cos(a), radius * math.sin(a)))
    return _line_strip(pts)


def _rounded_square_pts(
    lo: float, hi: float, radius: float, per_corner: int = 6
) -> list[tuple[float, float, float]]:
    """Контур квадрата в плоскости YZ от ``lo`` до ``hi`` со скруглёнными углами."""
    pts: list[tuple[float, float, float]] = []
    corners = [  # центр скругления и начальный угол дуги (против часовой стрелки)
        ((hi - radius, lo + radius), -90.0),
        ((hi - radius, hi - radius), 0.0),
        ((lo + radius, hi - radius), 90.0),
        ((lo + radius, lo + radius), 180.0),
    ]
    for (cy, cz), start in corners:
        for i in range(per_corner + 1):
            a = math.radians(start + 90.0 * i / per_corner)
            pts.append((0.0, cy + radius * math.cos(a), cz + radius * math.sin(a)))
    return pts


def _square_yz(lo: float, hi: float, radius: float) -> coin.SoSeparator:
    """Заполненный квадрат со скруглёнными углами в плоскости YZ (выпуклый многоугольник)."""
    pts = _rounded_square_pts(lo, hi, radius)
    sep = coin.SoSeparator()
    hints = coin.SoShapeHints()
    hints.vertexOrdering.setValue(coin.SoShapeHints.COUNTERCLOCKWISE)
    hints.shapeType.setValue(coin.SoShapeHints.UNKNOWN_SHAPE_TYPE)
    sep.addChild(hints)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    sep.addChild(coords)
    face = coin.SoFaceSet()
    face.numVertices.setValue(len(pts))
    sep.addChild(face)
    return sep


def _square_lines_yz(lo: float, hi: float, radius: float) -> coin.SoSeparator:
    """Обводка скруглённого квадрата и сетка 3×3 внутри (линии на 1/3 и 2/3 стороны)."""
    sep = coin.SoSeparator()
    outline = _rounded_square_pts(lo, hi, radius)
    sep.addChild(_line_strip([*outline, outline[0]]))
    third = (hi - lo) / 3.0
    for k in (1, 2):
        at = lo + third * k
        sep.addChild(_line_strip([(0.0, at, lo), (0.0, at, hi)]))
        sep.addChild(_line_strip([(0.0, lo, at), (0.0, hi, at)]))
    return sep


def arc_angles(style: HandleStyle) -> tuple[float, float]:
    """Концы дуги поворота, симметричные относительно 225° (8.1).

    На виде вдоль любой из двух осей плоскости дуга ложится на отрицательную полуось
    другой, и ближним к началу оказывается то один её конец, то другой. Видимый край
    каждого концевого шарика ставится на ``SHAFT_FROM`` от начала — вровень со стержнем
    стрелки, чтобы зазоры до шарика начала у стрелок и дуг совпадали. При радиусе 0,75·S
    и зазоре 0,20·S это ≈198,5°–251,5°.
    """
    near_end = SHAFT_FROM + style.px(ARC_END_DOT_PX / 2)
    half = math.degrees(math.acos(min(1.0, near_end / ARC_RADIUS)))
    return 270.0 - half, 180.0 + half


def _tube(
    a: tuple[float, float, float], b: tuple[float, float, float], radius: float
) -> coin.SoSeparator:
    """Цилиндр от ``a`` до ``b`` (ось цилиндра Coin — Y, поворачивается на отрезок)."""
    sep = coin.SoSeparator()
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    tr = coin.SoTranslation()
    tr.translation.setValue((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2)
    sep.addChild(tr)
    rot = coin.SoRotation()
    rot.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(dx, dy, dz)))
    sep.addChild(rot)
    cyl = coin.SoCylinder()
    cyl.radius.setValue(radius)
    cyl.height.setValue(length)
    sep.addChild(cyl)
    return sep


def _hit_shadow(handle: HandleId, style: HandleStyle) -> coin.SoSeparator | None:
    """Невидимая пикаемая тень ручки — хитбокс шире видимой геометрии.

    Стрелка — трубка от начала стержня до вершины конуса; дуга — цепочка цилиндров; кубик
    и шарик — сфера побольше. Квадрат плоскости и шарик начала без тени: по ним не
    промахиваются. Радиус пикинга FreeCAD (5 px) прибавляется к тени только у линий и
    точек, поэтому объёмные тени считаются «как есть».
    """
    kind = handle.kind
    sep = coin.SoSeparator()
    draw = coin.SoDrawStyle()
    if style.show_hitboxes:  # отладка: полупрозрачный пурпур, чтобы посмотреть геометрию тени
        draw.style.setValue(coin.SoDrawStyle.FILLED)
        color = coin.SoMaterial()
        color.diffuseColor.setValue(0.8, 0.0, 0.8)
        color.transparency.setValue(0.65)
        sep.addChild(color)
    else:
        draw.style.setValue(coin.SoDrawStyle.INVISIBLE)
    sep.addChild(draw)
    if kind is HandleKind.MOVE_AXIS:
        tip = SHAFT_TO + CONE_LEN + HIT_ARROW_OVERHANG
        sep.addChild(_tube((SHAFT_FROM, 0.0, 0.0), (tip, 0.0, 0.0), HIT_TUBE_RADIUS))
    elif kind is HandleKind.SCALE_AXIS:
        sep.addChild(_sphere_at(SCALE_BOX_AT, HIT_DOT_RADIUS))
    elif kind is HandleKind.EXTRUDE:
        sep.addChild(_sphere_at(EXTRUDE_DOT_AT, HIT_DOT_RADIUS))
    elif kind is HandleKind.ROTATE:
        from_deg, to_deg = hit_arc_angles(style)
        pts = [
            _arc_end(ARC_RADIUS, from_deg + (to_deg - from_deg) * i / HIT_ARC_SEGMENTS)
            for i in range(HIT_ARC_SEGMENTS + 1)
        ]
        for a, b in itertools.pairwise(pts):
            sep.addChild(_tube(a, b, HIT_TUBE_RADIUS))
    else:
        return None
    return sep


def hit_arc_angles(style: HandleStyle) -> tuple[float, float]:
    """Концы тени дуги: край концевого шарика плюс ``HIT_ARC_TAIL_DEG`` с каждой стороны."""
    from_deg, to_deg = arc_angles(style)  # ≈198,5° и 251,5° — центры концевых шариков
    dot_deg = math.degrees(style.px(ARC_END_DOT_PX / 2) / ARC_RADIUS)  # радиус шарика в градусах
    overhang = dot_deg + HIT_ARC_TAIL_DEG
    return from_deg - overhang, to_deg + overhang


def _geometry(
    handle: HandleId, style: HandleStyle
) -> tuple[coin.SoSeparator, float, list[tuple[coin.SoMaterial, float, bool]], dict]:
    """Геометрия ручки вдоль локальной X, базовая прозрачность, доп. материалы, узлы."""
    kind = handle.kind
    sep = coin.SoSeparator()
    transparency = style.transparency
    aux: list[tuple[coin.SoMaterial, float, bool]] = []
    extra: dict = {}
    shadow = _hit_shadow(handle, style)
    if shadow is not None:
        sep.addChild(shadow)
    if kind is HandleKind.MOVE_AXIS:
        sep.addChild(_line_strip([(SHAFT_FROM, 0, 0), (SHAFT_TO, 0, 0)]))
        sep.addChild(_cone_along_x(SHAFT_TO, CONE_LEN, CONE_RADIUS))
    elif kind is HandleKind.SCALE_AXIS:
        sep.addChild(_cube_at(SCALE_BOX_AT, 2 * CONE_RADIUS))  # ребро — диаметр конуса
    elif kind is HandleKind.EXTRUDE:
        sep.addChild(_sphere_at(EXTRUDE_DOT_AT, CONE_RADIUS))  # диаметр — как у конуса
    elif kind is HandleKind.ROTATE:
        from_deg, to_deg = arc_angles(style)
        sep.addChild(_arc_yz(ARC_RADIUS, from_deg, to_deg, ARC_SEGMENTS))
        for deg in (from_deg, to_deg):  # шарики на концах дуги, цвет оси (8.1)
            sep.addChild(_sphere_at_point(_arc_end(ARC_RADIUS, deg), style.px(ARC_END_DOT_PX / 2)))
    elif kind is HandleKind.MOVE_PLANE:
        radius = (PLANE_TO - PLANE_FROM) * PLANE_CORNER_FRACTION
        sep.addChild(_square_yz(PLANE_FROM, PLANE_TO, radius))
        transparency = max(transparency, PLANE_FILL_TRANSPARENCY)
        # обводка и сетка 3×3 — цвет ручки (красятся с ней), прозрачность не меньше
        # plane_transparency; заливка — общая прозрачность
        lines = coin.SoSeparator()
        color = coin.SoMaterial()
        color.diffuseColor.setValue(*style.axis_colors[handle.axis or 0])
        color.transparency.setValue(max(transparency, style.plane_transparency))
        aux.append((color, style.plane_transparency, True))
        lines.addChild(color)
        width = coin.SoDrawStyle()
        width.lineWidth.setValue(ORIGIN_OUTLINE_PX)
        lines.addChild(width)
        lines.addChild(_square_lines_yz(PLANE_FROM, PLANE_TO, radius))
        sep.addChild(lines)
    elif kind is HandleKind.MOVE_FREE:
        transparency = min(1.0, transparency + ORIGIN_EXTRA_TRANSPARENCY)
        sep.addChild(_sphere_at(0.0, style.px(style.origin_px)))
        # тёмный контур (8.1) — кольцо к камере (сцена поворачивает ``HandleNode.orient``);
        # сфера под полупрозрачным диском просвечивала бы сквозь него
        outline = coin.SoSeparator()
        orient = coin.SoRotation()
        outline.addChild(orient)
        color = coin.SoMaterial()  # своя прозрачность, цвет состоянием не меняется
        color.diffuseColor.setValue(*style.outline_color)
        color.transparency.setValue(max(transparency, ORIGIN_OUTLINE_TRANSPARENCY))
        aux.append((color, ORIGIN_OUTLINE_TRANSPARENCY, False))
        outline.addChild(color)
        width = coin.SoDrawStyle()
        width.lineWidth.setValue(ORIGIN_OUTLINE_PX)
        outline.addChild(width)
        outline.addChild(_circle_xy(style.px(style.origin_px + ORIGIN_OUTLINE_PX / 2)))
        sep.addChild(outline)
        extra["orient"] = orient
    else:
        raise ValueError(f"нет геометрии для {kind}")
    return sep, transparency, aux, extra


MAGNETIC_KINDS = frozenset(
    {HandleKind.MOVE_AXIS, HandleKind.ROTATE, HandleKind.SCALE_AXIS, HandleKind.EXTRUDE}
)
"""Ручки, к которым примагничивается курсор (8.5): тонкие и мелкие.

Квадрат плоскости большой — по нему не промахиваются, магнит только мешал бы (замечание
пользователя); шарик начала не тянут.
"""


def anchor_polyline(handle: HandleId, style: HandleStyle) -> list[tuple[float, float, float]]:
    """«Ось» ручки для примагничивания курсора (8.5) в координатах рамки, единицы S = 1.

    Кубик масштаба, шарик выдавливания и квадрат плоскости — одна точка (центр); стрелка —
    отрезок от начала стержня до конца тени за вершиной конуса; дуга — ломаная тени. У
    шарика начала оси нет. Какие из них магнитятся — :data:`MAGNETIC_KINDS`. Точки уже
    переставлены по оси ручки так же, как :func:`axis_matrix` переставляет геометрию.
    """
    kind = handle.kind
    local: list[tuple[float, float, float]]
    if kind is HandleKind.MOVE_AXIS:  # до конца тени: в «хвосте» курсор идёт на ось, не к вершине
        local = [(SHAFT_FROM, 0.0, 0.0), (SHAFT_TO + CONE_LEN + HIT_ARROW_OVERHANG, 0.0, 0.0)]
    elif kind is HandleKind.SCALE_AXIS:
        local = [(SCALE_BOX_AT, 0.0, 0.0)]
    elif kind is HandleKind.EXTRUDE:
        local = [(EXTRUDE_DOT_AT, 0.0, 0.0)]
    elif kind is HandleKind.MOVE_PLANE:
        mid = (PLANE_FROM + PLANE_TO) / 2.0
        local = [(0.0, mid, mid)]
    elif kind is HandleKind.ROTATE:
        from_deg, to_deg = hit_arc_angles(style)
        local = [
            _arc_end(ARC_RADIUS, from_deg + (to_deg - from_deg) * i / ARC_SEGMENTS)
            for i in range(ARC_SEGMENTS + 1)
        ]
    else:
        return []
    axis = handle.axis or 0
    out: list[tuple[float, float, float]] = []
    for x, y, z in local:
        v = [0.0, 0.0, 0.0]
        v[axis % 3], v[(axis + 1) % 3], v[(axis + 2) % 3] = x, y, z
        out.append((v[0], v[1], v[2]))
    return out


def base_color(handle: HandleId, style: HandleStyle) -> RGB:
    """Цвет ручки: цвет оси, начало — белое."""
    if handle.kind is HandleKind.MOVE_FREE:
        return style.origin_color
    return style.axis_colors[handle.axis or 0]


def build_handle(handle: HandleId, style: HandleStyle) -> HandleNode:
    """Собрать узлы ручки: ``SoSwitch(ax_…) → [ориентация оси] → SoTranslate1Dragger``.

    Части ``translator`` и ``translatorActive`` драггера — одна и та же геометрия (под
    разными сепараторами); подсветку задаёт :meth:`HandleNode.set_state`, а не драггер.
    """
    switch = coin.SoSwitch()
    switch.setName(node_name(handle))
    switch.whichChild.setValue(0)
    sep = coin.SoSeparator()
    switch.addChild(sep)
    if handle.axis is not None:
        orient = coin.SoMatrixTransform()
        orient.matrix.setValue(axis_matrix(handle.axis))
        sep.addChild(orient)
    dragger = coin.SoTranslate1Dragger()
    dragger.setName(node_name(handle))
    geom_root = coin.SoSeparator()
    light = (
        coin.SoLightModel()
    )  # плоский цвет: BASE_COLOR из корня сцены до частей драггера не доходит
    light.model.setValue(coin.SoLightModel.BASE_COLOR)
    geom_root.addChild(light)
    draw_style = coin.SoDrawStyle()
    draw_style.lineWidth.setValue(style.shaft_width_px)
    geom_root.addChild(draw_style)
    material = coin.SoMaterial()
    color = base_color(handle, style)
    material.diffuseColor.setValue(*color)
    geom_root.addChild(material)
    geometry, transparency, aux, extra = _geometry(handle, style)
    material.transparency.setValue(transparency)
    geom_root.addChild(geometry)
    dragger.setPart("translator", geom_root)
    # Один узел в обе части ``translatorSwitch`` Coin не пускает (предупреждение setPart, часть
    # остаётся стандартной — жёлтая двусторонняя стрелка при перетаскивании): для активной
    # части та же геометрия под отдельным сепаратором.
    active_root = coin.SoSeparator()
    active_root.addChild(geom_root)
    dragger.setPart("translatorActive", active_root)
    # собственная обратная связь драггера не нужна: направляющую рисует HUD (8.4)
    dragger.setPart("feedback", coin.SoSeparator())
    dragger.setPart("feedbackActive", coin.SoSeparator())
    sep.addChild(dragger)
    node = HandleNode(
        id=handle,
        root=switch,
        dragger=dragger,
        material=material,
        draw_style=draw_style,
        base_color=color,
        base_width=style.shaft_width_px,
        base_transparency=transparency,
        aux_materials=aux,
        orient=extra.get("orient"),
        geometry=geom_root,
    )
    return node


def all_handle_ids(kinds: frozenset[HandleKind] | None = None) -> list[HandleId]:
    """Полный набор ручек Gumball (по три на ось + начало), при ``kinds`` — фильтр.

    Порядок — порядок в графе, а он же порядок пикинга: при ``SHAPE_ON_TOP`` Coin не
    сортирует попадания по глубине, побеждает ручка, стоящая в графе раньше. Поэтому
    начало и маленькие ручки на стержне стрелки (масштаб, выдавливание) идут первыми.
    """
    ids: list[HandleId] = [HandleId(HandleKind.MOVE_FREE)]
    for kind in (
        HandleKind.SCALE_AXIS,
        HandleKind.EXTRUDE,
        HandleKind.MOVE_PLANE,
        HandleKind.MOVE_AXIS,
        HandleKind.ROTATE,
    ):
        ids.extend(HandleId(kind, axis) for axis in range(3))
    if kinds is None:
        return ids
    return [h for h in ids if h.kind in kinds]
