"""Протокол адаптера (7.1): классы данных и базовый класс.

Адаптер переводит намерение (``core.intent.Intent``) в изменения свойств конкретного типа
объектов. Ядро не знает типов объектов (принцип 5.1.1); всё, что нужно знать о ``Placement``,
``AttachmentOffset`` или сопряжениях сборки, живёт в адаптерах.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import FreeCAD as App

from ..core.intent import HandleKind, Intent
from ..core.target import TargetItem

Vector = App.Vector
Rotation = App.Rotation

ALL_AXES: frozenset[int] = frozenset({0, 1, 2})


@dataclass(frozen=True)
class Capabilities:
    """Что адаптер разрешает для элемента цели."""

    handles: frozenset[HandleKind]  # какие типы ручек показывать
    axes: frozenset[int] = ALL_AXES  # на каких осях рамки
    can_copy: bool = True
    disabled_reason: str | None = None  # задано — манипулятор серый, причина в подсказке


@dataclass(frozen=True)
class EditPoint:
    """Точка объекта, которую адаптер разрешает двигать отдельно (7.10)."""

    id: str  # устойчивый в пределах сессии идентификатор, например "v3"
    position: Vector  # глобальные координаты
    rotation: Rotation | None = None  # ориентация для Alignment.OBJECT
    capabilities: Capabilities | None = None  # ручки для точки; None — только перемещение


@dataclass(frozen=True)
class ParamSpec:
    """Параметр операции-ползунка (9.2.2)."""

    kind: type  # int или float
    default: int | float
    minimum: int | float
    maximum: int | float
    title: str  # подпись у курсора: "Сегментов"
    step: float | None = None  # шаг float-параметра на SliderStepPx; None — (max − min)/100


class OperationScope(Enum):
    """К чему применяется операция адаптера."""

    OBJECT = auto()
    POINT = auto()


@dataclass(frozen=True)
class OperationSpec:
    """Операция адаптера, вызываемая двойной буквой (9.2.1)."""

    id: str  # "extrude", "split", …
    scope: OperationScope
    key: str  # буква двойного сочетания: "E" → E, E
    title: str  # "Выдавить", "Разбить на сегменты"
    handles: frozenset[HandleKind]  # на каких ручках операция доступна
    param: ParamSpec | None = None  # задано — операция работает как ползунок
    points: frozenset[str] | None = None  # POINT: для каких точек доступна; None — для всех


@dataclass(frozen=True)
class FrameHint:
    """Предпочтительные начало и ориентация рамки от адаптера (12)."""

    origin: Vector | None = None
    rotation: Rotation | None = None


STANDARD_OPERATIONS: dict[str, str] = {"copy": "C", "extrude": "E", "split": "D"}
"""Буквы стандартных операций закреплены (9.2.1, решение 18)."""


@dataclass
class AdapterState:
    """Непрозрачное состояние адаптера на сессию: снимок исходного состояния элементов."""

    items: list[TargetItem] = field(default_factory=list)
    data: dict[str, object] = field(default_factory=dict)
    markers: list[Vector] = field(default_factory=list)  # маркеры результата ползунка (8.4)
    select_point: str | None = None  # точку с этим id выбрать после фиксации (7.8, EE)
    recompute_preview: bool = False  # предпросмотр меняет геометрию, не только Placement:
    # объекты пересчитываются во время перетаскивания даже при RecomputeDuringDrag = Never
    created_objects: list[str] = field(default_factory=list)  # объекты, созданные сессией
    # (например, выдавливание): пересчитываются в предпросмотре вместе с элементами цели
    select_objects: list[str] = field(default_factory=list)  # выделить после фиксации
    # (созданные операцией объекты, например выдавливание); пусто — выделение не менять


class Adapter:
    """Базовый класс адаптера. Методы по умолчанию — «ничего не умею»."""

    id: str = ""  # уникальное имя, например "axel.placement"
    priority: int = 0  # больше — предпочтительнее; адаптеры верстаков ≥ 100

    def supports(self, item: TargetItem) -> bool:
        """Берёт ли адаптер объект элемента цели."""
        return False

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Ручки, оси, копирование, причина недоступности."""
        return Capabilities(handles=frozenset())

    def frame_hint(self, item: TargetItem) -> FrameHint | None:
        """Предпочтительная рамка для элемента."""
        return None

    def edit_points(self, item: TargetItem) -> list[EditPoint]:
        """Точки редактирования объекта. Пустой список — точек нет."""
        return []

    def operations(self, item: TargetItem) -> list[OperationSpec]:
        """Операции адаптера, вызываемые двойными буквами."""
        return []

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок исходного состояния. Возвращает непрозрачное состояние адаптера."""
        return AdapterState(list(items))

    def constrain(self, state: AdapterState, intent: Intent) -> Intent:
        """Может изменить намерение: ограничить, округлить, привязать к узлам сети."""
        return intent

    def preview(self, state: AdapterState, intent: Intent) -> None:
        """Применить намерение к снимку. Вызывается многократно."""

    def commit(self, state: AdapterState, intent: Intent) -> list[str]:
        """Окончательно применить. Возвращает имена изменённых объектов для пересчёта."""
        return []

    def cancel(self, state: AdapterState) -> None:
        """Освободить ресурсы, не относящиеся к документу. Откат документа делает сессия."""

    def duplicate(self, state: AdapterState) -> AdapterState:
        """Создать копии элементов и вернуть новое состояние для них. Только при ``can_copy``."""
        raise NotImplementedError(f"адаптер {self.id} не поддерживает копирование")

    def operation_name(self, intent: Intent) -> str:
        """Название операции для истории отмены."""
        return "Axel"
