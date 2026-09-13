"""Математика манипуляций (раздел 10 спецификации).

Каждая формула — отдельная функция без побочных эффектов. Все величины в глобальных
координатах: длины в миллиметрах, углы в радианах. Направления считаются единичными.
Отказ (условия 10.2, 10.3, 10.5) выражается возвратом ``None``: вызывающий код игнорирует
событие и сохраняет прежнее намерение.

Модуль не импортирует ``FreeCADGui``, ``pivy`` и Qt (принцип 5.1.4). Единственное место,
где градусы встречаются с радианами, — :func:`rotation_from_axis_angle`.
"""

from __future__ import annotations

import math as _m

import FreeCAD as App

from . import constants

Vector = App.Vector
Rotation = App.Rotation
Placement = App.Placement
Matrix = App.Matrix


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------


def wrap_angle(angle: float) -> float:
    """Привести угол к диапазону (−π, π]."""
    a = _m.fmod(angle + _m.pi, constants.TWO_PI)
    if a <= 0.0:
        a += constants.TWO_PI
    return a - _m.pi


def rotation_from_axis_angle(axis: Vector, angle_rad: float) -> Rotation:
    """Поворот вокруг оси на угол в радианах.

    Конструктор ``App.Rotation(axis, angle)`` принимает градусы — это единственное место
    перевода (раздел 4).
    """
    return Rotation(axis, _m.degrees(angle_rad))


def drag_strength(percent: float) -> float:
    """Сила перетаскивания ``k`` (10.11): проценты → коэффициент."""
    return percent / 100.0


# ---------------------------------------------------------------------------
# 10.2 Перемещение по оси
# ---------------------------------------------------------------------------


def ray_axis_param(
    origin: Vector,
    direction: Vector,
    ray_point: Vector,
    ray_dir: Vector,
    eps: float = constants.PARALLEL_EPS,
) -> float | None:
    """Параметр ``t`` точки оси ``origin + t·direction``, ближайшей к лучу.

    Возвращает ``None``, если ось почти параллельна лучу (``1 − b² < eps``) или ближайшая
    точка луча лежит позади камеры (``s < 0``).
    """
    w = origin - ray_point
    b = direction.dot(ray_dir)
    f = direction.dot(w)
    e = ray_dir.dot(w)
    denom = 1.0 - b * b
    if denom < eps:
        return None
    t = (b * e - f) / denom
    s = (e - b * f) / denom
    if s < 0.0:
        return None
    return t


def axis_translation(t: float, t0: float, direction: Vector, strength: float = 1.0) -> Vector:
    """Смещение по оси от точки захвата: ``Δ = (t − t₀)·k·d`` (10.2)."""
    return direction * ((t - t0) * strength)


# ---------------------------------------------------------------------------
# 10.3 / 10.4 Перемещение в плоскости
# ---------------------------------------------------------------------------


def ray_plane_point(
    origin: Vector,
    normal: Vector,
    ray_point: Vector,
    ray_dir: Vector,
    min_sin: float = _m.sin(_m.radians(constants.DEGENERATE_ANGLE_DEG)),
) -> Vector | None:
    """Точка пересечения луча с плоскостью через ``origin`` с нормалью ``normal``.

    Возвращает ``None``, если плоскость видна почти с ребра (``|n·r| < sin θ``) или точка
    пересечения позади камеры.
    """
    nr = normal.dot(ray_dir)
    if abs(nr) < min_sin:
        return None
    s = normal.dot(origin - ray_point) / nr
    if s < 0.0:
        return None
    return ray_point + ray_dir * s


def plane_translation(point: Vector, point0: Vector, strength: float = 1.0) -> Vector:
    """Смещение в плоскости от точки захвата: ``Δ = (X − X₀)·k`` (10.3)."""
    return (point - point0) * strength


def plane_components(delta: Vector, u: Vector, v: Vector) -> tuple[float, float]:
    """Проекции смещения на оси плоскости ``u``, ``v``."""
    return delta.dot(u), delta.dot(v)


# ---------------------------------------------------------------------------
# 10.5 Поворот
# ---------------------------------------------------------------------------


def rotation_angle(
    origin: Vector,
    axis: Vector,
    point0: Vector,
    point: Vector,
    min_radius: float = 0.0,
) -> float | None:
    """Угол ``φ ∈ (−π, π]`` от ``point0`` к ``point`` вокруг ``axis`` через ``origin``.

    ``min_radius`` — расстояние от центра (в мировых единицах, соответствует 5 пикселям),
    ближе которого угол неустойчив: тогда возвращается ``None``.
    """
    v0 = point0 - origin
    v = point - origin
    if v.Length < min_radius or v0.Length < min_radius:
        return None
    return _m.atan2(axis.dot(v0.cross(v)), v0.dot(v))


def continuous_angle(theta_prev: float, phi: float) -> float:
    """Непрерывный угол: ``θ = θ_prev + wrap(φ − wrap(θ_prev))`` (10.5).

    Позволяет углу расти за пределы ±π без скачков при переходе через полуоборот.
    """
    return theta_prev + wrap_angle(phi - wrap_angle(theta_prev))


def screen_mode_angle(
    cursor_delta_px: tuple[float, float],
    tangent_px: tuple[float, float],
    radius_px: float,
) -> float:
    """Угол в экранном режиме (кольцо с ребра): проекция смещения мыши на касательную / радиус."""
    tx, ty = tangent_px
    n = _m.hypot(tx, ty)
    if n == 0.0 or radius_px <= 0.0:
        return 0.0
    along = (cursor_delta_px[0] * tx + cursor_delta_px[1] * ty) / n
    return along / radius_px


def ring_edge_on(axis: Vector, view_dir: Vector, min_sin: float) -> bool:
    """Кольцо поворота видно с ребра: ``|a·r_view| < sin θ`` (10.5)."""
    return abs(axis.dot(view_dir)) < min_sin


# ---------------------------------------------------------------------------
# 10.6 Масштаб
# ---------------------------------------------------------------------------


def scale_factor(
    t: float,
    t0: float,
    strength: float = 1.0,
    allow_mirror: bool = constants.ALLOW_MIRROR,
    min_scale: float = constants.MIN_SCALE,
    t0_eps: float = 1e-9,
) -> float | None:
    """Коэффициент масштаба по оси: ``f = 1 + (t/t₀ − 1)·k`` (10.6).

    При ``|t₀|`` около нуля коэффициент не определён — ``None``. Если ``f ≤ 0`` и
    зеркалирование запрещено, возвращается ``min_scale``.
    """
    if abs(t0) < t0_eps:
        return None
    f = 1.0 + (t / t0 - 1.0) * strength
    if f <= 0.0 and not allow_mirror:
        return min_scale
    return f


def scale_factor_2d(
    point: Vector, point0: Vector, origin: Vector, min_dist: float = 1e-9
) -> float | None:
    """Коэффициент масштаба в плоскости: ``f = |X − O| / |X₀ − O|`` (10.6)."""
    d0 = (point0 - origin).Length
    if d0 < min_dist:
        return None
    return (point - origin).Length / d0


# ---------------------------------------------------------------------------
# 10.7 Выдавливание, 10.10 Шаг, 10.8 Вырожденность и скачки
# ---------------------------------------------------------------------------


def extrude_distance(t: float, t0: float, strength: float = 1.0) -> float:
    """Расстояние выдавливания вдоль оси: ``(t − t₀)·k`` (10.7)."""
    return (t - t0) * strength


def apply_step(value: float, step: float) -> float:
    """Округление к сетке шага: ``round(value / step)·step`` (10.10); ``step ≤ 0`` — как есть."""
    if step <= 0.0:
        return value
    return round(value / step) * step


def degenerate_axis(
    direction: Vector, view_dir: Vector, angle_deg: float = constants.DEGENERATE_ANGLE_DEG
) -> bool:
    """Стрелка вырождена: угол между осью и направлением взгляда меньше ``θ`` (10.8)."""
    c = min(1.0, abs(direction.dot(view_dir)))
    return _m.degrees(_m.acos(c)) < angle_deg


def degenerate_plane(
    normal: Vector, view_dir: Vector, angle_deg: float = constants.DEGENERATE_ANGLE_DEG
) -> bool:
    """Плоскость вырождена: угол между плоскостью и направлением взгляда меньше ``θ`` (10.8)."""
    s = min(1.0, abs(normal.dot(view_dir)))
    return _m.degrees(_m.asin(s)) < angle_deg


def facing_plane(
    normals: list[Vector], view_dir: Vector, axes: frozenset[int] | None = None
) -> int | None:
    """Индекс плоскости (по нормали), больше всего обращённой к экрану (8.1, как в Rhino).

    Берётся наибольший ``|n·view_dir|`` среди осей из ``axes`` (все, если ``None``); при равенстве
    (изометрия) — плоскость с большим индексом, то есть XY рабочей рамки.
    """
    candidates = [a for a in range(len(normals)) if axes is None or a in axes]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (round(abs(normals[a].dot(view_dir)), 6), a))


def is_jump(
    delta_length: float, view_extent: float, factor: float = constants.JUMP_GUARD_FACTOR
) -> bool:
    """Защита от скачков у порога вырожденности (10.8)."""
    return delta_length > factor * view_extent


# ---------------------------------------------------------------------------
# 10.9 Экранный размер
# ---------------------------------------------------------------------------


def world_per_pixel_ortho(camera_height: float, viewport_height_px: float) -> float:
    """Размер пикселя в мировых единицах для ортографической камеры."""
    return camera_height / viewport_height_px


def world_per_pixel_perspective(
    origin: Vector,
    camera_pos: Vector,
    view_dir: Vector,
    height_angle: float,
    viewport_height_px: float,
) -> float:
    """Размер пикселя в мировых единицах в точке ``origin`` для перспективной камеры."""
    dist = (origin - camera_pos).dot(view_dir)
    return 2.0 * dist * _m.tan(height_angle / 2.0) / viewport_height_px


# ---------------------------------------------------------------------------
# 10.13 Ползунок
# ---------------------------------------------------------------------------


def slider_value(
    cursor_delta_px: tuple[float, float],
    screen_dir_px: tuple[float, float] | None,
    default: float,
    minimum: float,
    maximum: float,
    step_px: float = constants.SLIDER_STEP_PX,
    is_int: bool = True,
    float_step: float | None = None,
) -> int | float:
    """Значение ползунка по экранному смещению (10.13).

    ``screen_dir_px`` — экранное направление ручки; ``None`` — вырождено, тогда используется
    вертикаль экрана (вверх — больше; ось y считается направленной вверх, как в Coin).
    """
    if screen_dir_px is None:
        ex, ey = 0.0, 1.0
    else:
        n = _m.hypot(*screen_dir_px)
        ex, ey = (0.0, 1.0) if n == 0.0 else (screen_dir_px[0] / n, screen_dir_px[1] / n)
    along = cursor_delta_px[0] * ex + cursor_delta_px[1] * ey
    steps = round(along / step_px)
    if is_int:
        value: int | float = int(default) + steps
    else:
        inc = float_step if float_step is not None else (maximum - minimum) / 100.0
        value = default + steps * inc
    return max(minimum, min(maximum, value))


def clamp_param(value: float, spec: object) -> int | float:
    """Точное значение ползунка из числового ввода: к типу параметра и в его границы (9.2.2).

    ``spec`` — ``ParamSpec`` с полями ``kind``, ``minimum``, ``maximum``.
    """
    if spec.kind is int:
        value = round(value)
    return max(spec.minimum, min(spec.maximum, value))


# ---------------------------------------------------------------------------
# Формулы адаптеров (7.5, 7.6): L' = P⁻¹·D·P·L
# ---------------------------------------------------------------------------


def local_after_global(parent: Matrix, delta: Matrix, local: Placement) -> Placement:
    """Новое локальное положение при глобальном преобразовании ``D``: ``L' = P⁻¹·D·P·L``.

    ``parent`` — накопленная матрица контейнеров (для присоединения — ``P·A``), ``local`` —
    редактируемое свойство (``Placement`` или ``AttachmentOffset``). Глобальное положение
    после применения равно ``D·G``, где ``G = P·L``.
    """
    m = parent.inverse() * delta * parent * local.toMatrix()
    return Placement(m)


def global_matrix(parent: Matrix, local: Placement) -> Matrix:
    """``G = P·L``."""
    return parent * local.toMatrix()


def parent_matrix(global_placement: Placement, local: Placement) -> Matrix:
    """``P = G·L⁻¹`` — родительская матрица из глобального положения и локального свойства."""
    return global_placement.toMatrix() * local.toMatrix().inverse()
