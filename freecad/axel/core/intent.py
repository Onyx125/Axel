"""Намерение (6.3, 6.4): что хочет сделать пользователь, в терминах рамки.

Намерение не зависит от типа объекта и всегда отсчитывается от начала сессии
(принцип 5.1.2): полный сдвиг, полный угол, полный коэффициент. Матрица ``D`` — глобальное
преобразование, которое адаптеры переводят в изменения свойств.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import FreeCAD as App

from . import math as axmath
from .frame import Frame

Vector = App.Vector
Matrix = App.Matrix


class HandleKind(Enum):
    """Типы ручек виджета (6.3)."""

    MOVE_AXIS = auto()  # стрелка
    MOVE_PLANE = auto()  # квадрат Move 2D
    MOVE_FREE = auto()  # начало манипулятора
    ROTATE = auto()  # дуга
    SCALE_AXIS = auto()  # квадратик на оси
    EXTRUDE = auto()  # точка выдавливания
    MENU = auto()  # устарело: значка меню нет, меню — ПКМ по началу; в наборе ручек игнорируется


@dataclass(frozen=True)
class HandleId:
    """Ручка: тип и ось рамки (для MOVE_PLANE — индекс нормали)."""

    kind: HandleKind
    axis: int | None = None


class Operation(Enum):
    """Вид преобразования."""

    TRANSLATE = auto()
    ROTATE = auto()
    SCALE = auto()
    EXTRUDE = auto()
    PARAMETER = auto()  # ползунок операции адаптера


class Source(Enum):
    """Откуда пришло намерение."""

    DRAG = auto()
    NUMERIC = auto()


def _zero() -> Vector:
    return Vector(0, 0, 0)


@dataclass(frozen=True)
class Intent:
    """Описание преобразования от начала сессии (6.4)."""

    operation: Operation
    handle: HandleId
    frame: Frame  # рамка на начало сессии
    translation: Vector = field(default_factory=_zero)  # TRANSLATE, глобально
    axis: Vector | None = None  # ROTATE, EXTRUDE, SCALE по оси: ось ручки, глобально
    angle: float = 0.0  # ROTATE: радианы
    center: Vector | None = None  # ROTATE, SCALE: центр, глобально
    factors: tuple[float, float, float] = (1.0, 1.0, 1.0)  # SCALE: по осям рамки
    distance: float = 0.0  # EXTRUDE: мм
    both_sides: bool = False  # EXTRUDE
    copy: bool = False  # операция «копия» (CC)
    op_id: str | None = None  # операция адаптера: "extrude", "split", …
    value: int | float | None = None  # PARAMETER: значение ползунка
    point_id: str | None = None  # точка редактирования
    step: bool = False  # действовал ли шаг
    source: Source = Source.DRAG

    def matrix(self) -> Matrix:
        """Глобальная матрица ``D`` для TRANSLATE, ROTATE, SCALE: ``G' = D·G``.

        Для EXTRUDE и PARAMETER матрица не определена — ``ValueError``.
        """
        if self.operation is Operation.TRANSLATE:
            return translation_matrix(self.translation)
        if self.operation is Operation.ROTATE:
            if self.axis is None:
                raise ValueError("ROTATE: не задана ось")
            return rotation_matrix(self.axis, self.angle, self.center or self.frame.origin)
        if self.operation is Operation.SCALE:
            return scale_matrix(self.frame, self.factors, self.center or self.frame.origin)
        raise ValueError(f"матрица не определена для {self.operation.name}")

    def is_identity(self, tol: float = 1e-12) -> bool:
        """Намерение ничего не меняет (нулевой сдвиг, угол, единичные коэффициенты)."""
        if self.operation is Operation.TRANSLATE:
            return self.translation.Length <= tol
        if self.operation is Operation.ROTATE:
            return abs(self.angle) <= tol
        if self.operation is Operation.SCALE:
            return all(abs(f - 1.0) <= tol for f in self.factors)
        if self.operation is Operation.EXTRUDE:
            return abs(self.distance) <= tol
        return self.value is None


# ---------------------------------------------------------------------------
# Построение матриц. Соглашение FreeCAD: ``A * B`` применяет сначала B, потом A.
# ---------------------------------------------------------------------------


def translation_matrix(delta: Vector) -> Matrix:
    """``D = T(Δ)``."""
    m = Matrix()
    m.move(delta)
    return m


def rotation_matrix(axis: Vector, angle_rad: float, center: Vector) -> Matrix:
    """``D = T(c)·R(a, φ)·T(−c)``."""
    r = axmath.rotation_from_axis_angle(axis, angle_rad).toMatrix()
    return _translate(center) * r * _translate(-center)


def scale_matrix(frame: Frame, factors: tuple[float, float, float], center: Vector) -> Matrix:
    """``D = T(c)·R·S(f)·R⁻¹·T(−c)`` — масштаб по осям рамки относительно центра."""
    r = frame.rotation.toMatrix()
    s = Matrix()
    s.scale(*factors)
    return _translate(center) * r * s * r.inverse() * _translate(-center)


def _translate(delta: Vector) -> Matrix:
    m = Matrix()
    m.move(delta)
    return m
