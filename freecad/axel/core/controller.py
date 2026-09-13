"""Автомат состояний взаимодействия (9.1) и связка «вид → математика → сессия → адаптеры».

Контроллер не импортирует ``FreeCADGui``, ``pivy`` и Qt: сцена (``view.scene``) и окружение
вида (``view.events``) внедряются через конструктор, поэтому автомат тестируется без
интерфейса с поддельными сценой и окружением (правило зависимостей 5.2).
"""

from __future__ import annotations

import math as _m
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Protocol

import FreeCAD as App

from ..adapters.base import (
    STANDARD_OPERATIONS,
    Capabilities,
    EditPoint,
    OperationScope,
    OperationSpec,
)
from ..adapters.registry import (
    AdapterGroup,
    Registry,
    combined_capabilities,
    combined_operations,
)
from . import constants
from . import frame as axframe
from . import math as axmath
from . import target as axtarget
from .events import Events, SuppressionRules, events, suppression
from .frame import Alignment, Frame, OriginMode
from .i18n import tr
from .intent import HandleId, HandleKind, Intent, Operation, Source
from .session import DragSession, new_session
from .target import Target

Vector = App.Vector


class State(Enum):
    """Состояния автомата 9.1 (числовой ввод, меню, перенос начала — этапы 2–3)."""

    HIDDEN = auto()
    SHOWN = auto()
    SUPPRESSED = auto()
    HOVER = auto()
    DRAGGING = auto()
    NUMERIC = auto()  # поле ввода показано (9.3)


@dataclass
class Settings:
    """Настройки, влияющие на математику (15.4); читает и передаёт ``gui.preferences``."""

    drag_strength_percent: float = constants.DRAG_STRENGTH_PERCENT
    move_step_mm: float = constants.MOVE_STEP_MM
    angle_step_deg: float = constants.ANGLE_STEP_DEG
    scale_step: float = constants.SCALE_STEP
    allow_mirror: bool = constants.ALLOW_MIRROR
    degenerate_angle_deg: float = constants.DEGENERATE_ANGLE_DEG
    step_enabled: bool = False
    auto_reset: bool = True
    deselect_new_objects: bool = True  # снимать выделение, сделанное командой создания (13.2)
    alignment: Alignment = Alignment.WORKPLANE  # умолчание — как в Rhino (12.2)
    origin_mode: OriginMode = OriginMode.BOUNDING_BOX_CENTER
    show_tooltips: bool = True
    tooltip_delay_ms: int = constants.TOOLTIP_DELAY_MS
    shown_kinds: frozenset[HandleKind] = frozenset(HandleKind)  # группы ручек (15.4)
    ring_radius_px: float = (
        constants.ARC_RADIUS_FRACTION * constants.SIZE_PX
    )  # экранный режим (10.5)
    mod_step: str = constants.MOD_STEP  # модификатор временной инверсии шага (9.2)
    mod_shape: str = constants.MOD_SHAPE  # геометрическое уточнение: равномерный масштаб и т. п.
    slider_step_px: int = constants.SLIDER_STEP_PX  # пикселей на шаг ползунка (10.13)
    recompute_during_drag: str = "Never"  # Never, Throttled, Always (11.2)
    recompute_throttle_ms: int = constants.RECOMPUTE_THROTTLE_MS
    proxy_preview_threshold: int = constants.PROXY_PREVIEW_THRESHOLD


class SceneLike(Protocol):
    """Что контроллеру нужно от ``view.scene.ManipulatorScene``."""

    def show(self) -> None:
        """См. реализацию в view."""

    def hide(self) -> None:
        """См. реализацию в view."""

    def set_frame(self, frame: Frame) -> None:
        """См. реализацию в view."""

    def set_available(self, kinds: frozenset[HandleKind], axes: frozenset[int]) -> None:
        """См. реализацию в view."""

    def set_hidden_per_view(self, degenerate: Callable[[Vector], set[HandleId]]) -> None:
        """См. реализацию в view: в каждом виде — свой набор скрытых ручек (13.4)."""

    def set_state(self, handle_id: HandleId, state: object) -> None:
        """См. реализацию в view."""

    def set_all_states(self, state: object) -> None:
        """См. реализацию в view."""

    def set_drag_states(self, active: HandleId) -> None:
        """См. реализацию в view."""

    def cursor_position(self, handle_id: HandleId) -> tuple[int, int] | None:
        """См. реализацию в view."""

    def event_modifiers(self, handle_id: HandleId) -> frozenset[str]:
        """См. реализацию в view: модификаторы текущего события драггера (9.2)."""

    def set_edit_points(self, positions: list[Vector], selected: int | None = None) -> None:
        """См. реализацию в view: маркеры точек редактирования (7.10)."""

    def clear_edit_points(self) -> None:
        """См. реализацию в view."""

    def show_proxy(self, minimum: Vector, maximum: Vector) -> None:
        """См. реализацию в view: каркас габаритов вместо объектов (11.2)."""

    def move_proxy(self, matrix: App.Matrix) -> None:
        """См. реализацию в view."""

    def hide_proxy(self) -> None:
        """См. реализацию в view."""

    def set_relocating(self, on: bool) -> None:
        """См. реализацию в view."""

    def update_hud(self, intent: Intent, frame: Frame, **kwargs: object) -> None:
        """См. реализацию в view."""

    def clear_hud(self) -> None:
        """См. реализацию в view."""

    def set_armed_label(self, text: str | None) -> None:
        """См. реализацию в view: метка взведённой операции у начала (8.4)."""


class EnvironmentLike(Protocol):
    """Что контроллеру нужно от вида и документа (``view.events.ViewEnvironment``)."""

    def active_document(self) -> App.Document | None:
        """См. реализацию в view."""

    def selection(self, doc_name: str) -> list[tuple[str, str]]:
        """См. реализацию в view."""

    def ray(self, px: tuple[int, int]) -> tuple[Vector, Vector] | None:
        """См. реализацию в view."""

    def view_direction(self) -> Vector:
        """См. реализацию в view."""

    def screen_basis(self) -> tuple[Vector, Vector]:
        """Мировые орты экранных осей (вправо, вверх) — экранный режим (10.5), рамка по виду."""

    def modifiers(self) -> frozenset[str]:
        """Нажатые модификаторы: подмножество ``{"ctrl", "shift", "alt", "meta"}`` (9.2)."""

    def world_per_pixel(self, point: Vector) -> float:
        """См. реализацию в view."""

    def is_suppressed(self) -> bool:
        """См. реализацию в view."""

    def recompute(self, doc: App.Document, names: list[str]) -> None:
        """См. реализацию в view."""

    def status(self, text: str) -> None:
        """См. реализацию в view."""

    def report(self, text: str) -> None:
        """См. реализацию в view."""

    def show_numeric(
        self,
        kind: str,
        initial: str,
        px: tuple[int, int] | None,
        on_accept: object,
        on_cancel: object,
    ) -> None:
        """См. реализацию в view."""

    def hide_numeric(self) -> None:
        """См. реализацию в view."""

    def show_menu(self, px: tuple[int, int] | None) -> None:
        """Меню манипулятора у точки ``px`` (пиксели Coin) или у курсора (9.5)."""

    def select(self, doc_name: str, names: list[str]) -> None:
        """Заменить выделение на перечисленные объекты (решение 11)."""

    def now_ms(self) -> float:
        """Монотонное время в миллисекундах (политика пересчёта 11.2)."""


class WorkplaneLike(Protocol):
    """Провайдер рабочей плоскости (``input.workplane``)."""

    def rotation(self) -> App.Rotation | None:
        """Поворот рабочей плоскости или ``None``."""


NUMERIC_KINDS = {
    HandleKind.MOVE_AXIS: "length",
    HandleKind.ROTATE: "angle",
    HandleKind.SCALE_AXIS: "factor",
}
"""Ручки с числовым вводом по щелчку (9.3) и вид величины."""

DRAG_NUMERIC_KINDS = {
    **NUMERIC_KINDS,
    HandleKind.EXTRUDE: "length",
    HandleKind.MOVE_PLANE: "length",
}
"""Ручки, у которых цифры во время перетаскивания открывают поле (F-12)."""

NUMBER_KIND = "number"
"""Вид величины поля ввода для ползунка: безразмерное число (9.2.2)."""

NUMERIC_KEYS = set("0123456789-=.,")

ALIGNMENT_CYCLE = (Alignment.WORLD, Alignment.WORKPLANE, Alignment.OBJECT, Alignment.VIEW)
"""Порядок циклического переключения (F-15)."""

COPY_OPERATION = OperationSpec(
    id="copy",
    scope=OperationScope.OBJECT,
    key=STANDARD_OPERATIONS["copy"],
    title="Copy",
    handles=frozenset(
        {HandleKind.MOVE_AXIS, HandleKind.MOVE_PLANE, HandleKind.MOVE_FREE, HandleKind.ROTATE}
    ),
)
"""Копия — операция ядра: сессия вызывает ``duplicate`` адаптеров (9.2.1, F-13)."""

OPERATION_TITLES: dict[str, str] = {"copy": "copy", "extrude": "extrude", "split": "split"}


def _with_operation(intent: Intent, op_id: str | None) -> Intent:
    """Проставить в намерение операцию сессии (9.2.1)."""
    if op_id is None:
        return intent
    if op_id == "copy":
        return replace(intent, copy=True)
    return replace(intent, op_id=op_id)


def _title(op_id: str) -> str:
    """Название операции для строки состояния."""
    return tr(OPERATION_TITLES.get(op_id, op_id))


class HandleStates:
    """Имена состояний ручек, чтобы ядро не импортировало ``view.handles``."""

    NORMAL = "NORMAL"
    HOVER = "HOVER"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class ScreenGrab:
    """Захват дуги в экранном режиме (10.5): пиксель захвата, экранная касательная, радиус в px."""

    px: tuple[int, int]
    tangent_px: tuple[float, float]
    radius_px: float


@dataclass(frozen=True)
class SliderGrab:
    """Захват ползунка (10.13): пиксель нажатия, экранное направление ручки, спецификация."""

    px: tuple[int, int]
    direction_px: tuple[float, float] | None  # None — вырождено, используется вертикаль
    spec: OperationSpec


class Controller:
    """Связывает выделение, рамку, ручки, математику намерения и сессию."""

    def __init__(
        self,
        registry: Registry,
        scene: SceneLike,
        env: EnvironmentLike,
        settings: Settings | None = None,
        workplane: WorkplaneLike | None = None,
    ) -> None:
        """Контроллер с внедрёнными реестром, сценой и окружением; выключен до :meth:`enable`."""
        self.registry = registry
        self.scene = scene
        self.env = env
        self.settings = settings or Settings()
        self.workplane = workplane
        self.enabled = False
        self.state = State.HIDDEN
        self.target: Target | None = None
        self.frame: Frame | None = None
        self.groups: list[AdapterGroup] = []
        self.caps: Capabilities | None = None
        self.session: DragSession | None = None
        self.hover_handle: HandleId | None = None
        self._drag_cancelled = False
        self._drag_mods: frozenset[str] = frozenset()  # модификаторы текущей сессии (9.2)
        self.armed_op: str | None = None  # взведённая операция до перетаскивания (9.2.1)
        self.points: list[EditPoint] = []  # точки редактирования цели (7.10)
        self._proxy = False  # упрощённый предпросмотр текущей сессии (11.2)
        self._last_recompute_ms = float("-inf")
        self._theta = 0.0  # непрерывный угол поворота (10.5)
        self.before_refresh: object = None  # рантайм: привязать сцену к активному виду
        self.relocating = False  # режим переноса начала (9.4)
        self._relocate_backup: Frame | None = None
        self._relocate_base: Frame | None = None
        self._relocate_grab: object = None
        self.relocated: dict[tuple[tuple[str, ...], ...], App.Placement] = {}  # 12.4
        self._numeric: dict | None = None  # {'handle', 'sign'} пока показано поле ввода
        self.events: Events = events  # события для верстаков (16.1)
        self.suppression: SuppressionRules = suppression  # правила подавления (16.1)
        self.on_operations: Callable[[list[OperationSpec]], None] | None = None  # 15.1
        self._last_target_key: object = None  # для события target_changed
        self._created: set[str] = set()  # объекты, созданные в текущем цикле событий (13.2)
        self._auto_selected: set[str] = set()  # из них выделенные командой в том же цикле

    # ------------------------------------------------------------------ включение

    def enable(self) -> None:
        """Включить манипулятор и построить его по текущему выделению."""
        self.enabled = True
        self.refresh()

    def disable(self) -> None:
        """Выключить: прервать сессию с откатом, скрыть виджет (13.5)."""
        self._abort_session()
        self.enabled = False
        self._hide()

    # ------------------------------------------------------------------ показ

    def refresh(self) -> None:
        """Перестроить цель и рамку по выделению и условиям подавления (9.1, 12.3)."""
        if not self.enabled or self.session is not None:
            return
        if self.before_refresh is not None:
            self.before_refresh()
        if self.env.is_suppressed() or self.suppression.active():
            self._hide(State.SUPPRESSED)
            return
        doc = self.env.active_document()
        if doc is None:
            self._hide()
            return
        target = axtarget.make_target(
            doc, self.env.selection(doc.Name), self.registry.supports_path
        )
        if target is None:
            self._hide()
            return
        target = self._keep_point(target)
        self.target = target
        self.groups = self.registry.groups(target)
        self.caps = combined_capabilities(self.groups)
        self._announce_operations()
        self._refresh_points()
        point = self.selected_point()
        if point is not None and point.capabilities is not None:
            self.caps = point.capabilities  # ручки точки (7.10)
        self.frame = self.remembered_frame(target) or self.default_frame(target)
        self.scene.set_frame(self.frame)
        self.scene.set_available(self.shown_handles(), self.caps.axes)
        self.scene.set_hidden_per_view(self.degenerate_handles)
        self.scene.set_all_states(
            HandleStates.DISABLED if self.caps.disabled_reason else HandleStates.NORMAL
        )
        if self.caps.disabled_reason:
            self.env.status(f"Axel: {self.caps.disabled_reason}")
        self.scene.show()
        self.scene.set_armed_label(self._armed_label())
        self.state = State.SHOWN
        self.hover_handle = None
        self._emit_target_changed()

    def default_frame(self, target: Target) -> Frame:
        """Рамка по правилам 12.1–12.2; для выбранной точки — её положение (7.10)."""
        rotation = None
        if self.settings.alignment is Alignment.WORKPLANE and self.workplane is not None:
            rotation = self.workplane.rotation()
        basis = self.env.screen_basis() if self.settings.alignment is Alignment.VIEW else None
        frame = axframe.default_frame(
            target, self.settings.alignment, self.settings.origin_mode, rotation, basis
        )
        frame = self._apply_frame_hints(target, frame)
        point = self.selected_point()
        if point is None:
            return frame
        rotation = frame.rotation
        if self.settings.alignment is Alignment.OBJECT and point.rotation is not None:
            rotation = point.rotation
        return Frame(point.position, rotation, frame.alignment, frame.relocated)

    def _apply_frame_hints(self, target: Target, frame: Frame) -> Frame:
        """Подсказки адаптеров (12.1, п. 3; 12.2): начало и ориентация «по объекту».

        Несколько элементов с подсказками начала — центр их габаритов. Ориентацию задаёт
        подсказка активного элемента, только в режиме «По объекту».
        """
        origins: list[Vector] = []
        rotation = None
        for group in self.groups:
            for item in group.items:
                try:
                    hint = group.adapter.frame_hint(item)
                except Exception as exc:  # noqa: BLE001 — принцип 5.1.6
                    self.env.report(
                        tr("Axel: frame_hint() of adapter {} failed: {}").format(
                            group.adapter.id, repr(exc)
                        )
                        + "\n"
                    )
                    continue
                if hint is None:
                    continue
                if hint.origin is not None:
                    origins.append(hint.origin)
                if hint.rotation is not None and item == target.active:
                    rotation = hint.rotation
        origin = frame.origin
        if origins:
            lo = Vector(
                min(p.x for p in origins), min(p.y for p in origins), min(p.z for p in origins)
            )
            hi = Vector(
                max(p.x for p in origins), max(p.y for p in origins), max(p.z for p in origins)
            )
            origin = (lo + hi) * 0.5
        if rotation is None or self.settings.alignment is not Alignment.OBJECT:
            rotation = frame.rotation
        return Frame(origin, rotation, frame.alignment, frame.relocated)

    # ------------------------------------------------------------------ выравнивание (F-14, F-15)

    @property
    def alignment(self) -> Alignment:
        """Текущий режим выравнивания."""
        return self.settings.alignment

    def set_alignment(self, alignment: Alignment) -> None:
        """Сменить режим выравнивания и перестроить рамку (12.3)."""
        self.settings.alignment = alignment
        if self.session is None:
            self.refresh()
        if self.visible and alignment is Alignment.OBJECT and self.target and len(self.target) > 1:
            self.env.status(
                tr("Axel: axes follow object {}").format(self.target.active.object().Label)
            )

    # ------------------------------------------------------------------ точки (7.10, F-23)

    def _refresh_points(self) -> None:
        """Точки редактирования цели: только при одном выделенном элементе (7.10, п. 4)."""
        self.points = []
        target = self.target
        if target is None or len(target) != 1:
            self.scene.clear_edit_points()
            return
        item = target.items[0]
        for group in self.groups:
            if item in group.items:
                self.points = list(group.adapter.edit_points(item))
                break
        if not self.points:
            self.scene.clear_edit_points()
            return
        ids = [p.id for p in self.points]
        if target.point_id is not None and target.point_id not in ids:
            self.target = replace(target, point_id=None)  # точка исчезла после фиксации (7.10)
        selected = self.point_index()
        self.scene.set_edit_points([p.position for p in self.points], selected)

    def _keep_point(self, target: Target) -> Target:
        """Сохранить выбранную точку при пересборке цели того же объекта (7.10)."""
        previous = self.target
        if previous is None or previous.point_id is None:
            return target
        if self._memory_key(previous) != self._memory_key(target):
            return target
        return replace(target, point_id=previous.point_id)

    def point_index(self) -> int | None:
        """Индекс выбранной точки среди точек цели."""
        if self.target is None or self.target.point_id is None:
            return None
        return next((i for i, p in enumerate(self.points) if p.id == self.target.point_id), None)

    def selected_point(self) -> EditPoint | None:
        """Выбранная точка редактирования или ``None``."""
        index = self.point_index()
        return self.points[index] if index is not None else None

    def select_point(self, index: int) -> bool:
        """Щелчок по маркеру: манипулятор переходит в точку (7.10, п. 2).

        Выделение FreeCAD не меняется — в дереве и свойствах остаётся объект.
        """
        if self.target is None or not (0 <= index < len(self.points)):
            return False
        point = self.points[index]
        if self.target.point_id == point.id:
            return True
        self.target = replace(self.target, point_id=point.id)
        self.disarm_operation()  # область действия операций сменилась (7.10)
        self.refresh()
        return True

    def clear_point(self) -> bool:
        """Щелчок по объекту или Esc: манипулятор возвращается к объекту (7.10, п. 3)."""
        if self.target is None or self.target.point_id is None:
            return False
        self.target = replace(self.target, point_id=None)
        self.disarm_operation()
        self.refresh()
        return True

    # ------------------------------------------------------------------ операции (9.2.1, F-31)

    def operations(self) -> list[OperationSpec]:
        """Операции, доступные для текущей цели: «копия» ядра плюс операции адаптеров."""
        if self.target is None or self.caps is None:
            return []
        specs: list[OperationSpec] = []
        if self.caps.can_copy:
            specs.append(COPY_OPERATION)
        point_id = self.target.point_id
        scope = OperationScope.POINT if point_id else OperationScope.OBJECT
        for spec in combined_operations(self.groups):
            if spec.scope is not scope:
                continue
            if spec.points is not None and point_id not in spec.points:
                continue  # операция не для этой точки (например, EE внутренней вершины, 7.8)
            specs.append(spec)
        return specs

    def operation(self, op_id: str) -> OperationSpec | None:
        """Спецификация доступной операции по идентификатору."""
        return next((s for s in self.operations() if s.id == op_id), None)

    def arm_operation(self, op_id: str) -> bool:
        """Взвести операцию до перетаскивания; повторный вызов снимает её (9.2.1).

        Возвращает ``True``, если операция взведена или снята; ``False`` — недоступна.
        """
        if self.session is not None or not self.visible:
            return False
        if self.armed_op == op_id:
            self.disarm_operation()
            self.env.status(tr('Axel: operation "{}" cleared').format(_title(op_id)))
            return True
        spec = self.operation(op_id)
        if spec is None:
            reason = (
                tr("nothing is selected")
                if self.target is None
                else tr("not available for this target")
            )
            self.env.status(tr('Axel: operation "{}" — {}').format(_title(op_id), reason))
            return False
        self.armed_op = op_id
        self.events.operation_armed.emit(op_id)
        self.scene.set_armed_label(self._armed_label())
        self.env.status(tr("Axel: {} — drag a handle").format(tr(spec.title)))
        return True

    def disarm_operation(self) -> None:
        """Снять взведённую операцию (Esc, смена выделения, после перетаскивания)."""
        if self.armed_op is not None:
            self.armed_op = None
            self.events.operation_armed.emit(None)
            self.scene.set_armed_label(None)

    def _armed_label(self) -> str | None:
        """Текст метки у начала манипулятора: название взведённой операции (8.4)."""
        if self.armed_op is None:
            return None
        spec = self.operation(self.armed_op)
        return tr(spec.title) if spec is not None else _title(self.armed_op)

    def _announce_operations(self) -> None:
        """Сообщить интерфейсу обо всех операциях цели: команды создаются автоматически (15.1)."""
        if self.on_operations is None:
            return
        try:
            self.on_operations(combined_operations(self.groups))
        except Exception as exc:  # noqa: BLE001 — принцип 5.1.6
            self.env.report(tr("Axel: operation commands failed: {}").format(repr(exc)) + "\n")

    def _emit_target_changed(self) -> None:
        key = None
        if self.target is not None:
            key = (self._memory_key(self.target), self.target.point_id)
        if key != self._last_target_key:
            self._last_target_key = key
            self.events.target_changed.emit(self.target)

    # ------------------------------------------------------------------ шаг (F-22, 9.2, 10.10)

    @property
    def step_enabled(self) -> bool:
        """Переключатель шага (настройка ``StepEnabled``)."""
        return self.settings.step_enabled

    def set_step(self, enabled: bool) -> None:
        """Включить или выключить шаг; во время сессии предпросмотр пересчитывается."""
        if enabled == self.settings.step_enabled:
            return
        self.settings.step_enabled = enabled
        self.on_modifiers_changed()

    def toggle_step(self) -> bool:
        """Переключить шаг; возвращает новое состояние."""
        self.set_step(not self.settings.step_enabled)
        return self.settings.step_enabled

    def modifiers(self) -> frozenset[str]:
        """Модификаторы: во время перетаскивания — из события драггера, иначе из окружения."""
        if self.state is State.DRAGGING:
            return self._drag_mods
        return self.env.modifiers()

    def step_active(self) -> bool:
        """Шаг с учётом модификатора: Ctrl временно инвертирует переключатель (9.2)."""
        return self.settings.step_enabled != (self.settings.mod_step in self.modifiers())

    def on_modifiers_changed(self, modifiers: frozenset[str] | None = None) -> None:
        """Модификатор нажат или отпущен во время перетаскивания — пересчитать намерение.

        ``modifiers`` задаются событием клавиатуры: событие драггера хранит состояние на
        момент последнего движения мыши и о нажатии клавиши ещё не знает.
        """
        if self.state is not State.DRAGGING or self.session is None:
            return
        if modifiers is not None:
            self._drag_mods = modifiers
        self.on_drag_motion(self.session.handle, keep_modifiers=modifiers is not None)

    def cycle_alignment(self) -> Alignment:
        """Следующий режим: мир → рабочая плоскость → объект → мир."""
        i = (
            ALIGNMENT_CYCLE.index(self.settings.alignment)
            if self.settings.alignment in ALIGNMENT_CYCLE
            else 0
        )
        self.set_alignment(ALIGNMENT_CYCLE[(i + 1) % len(ALIGNMENT_CYCLE)])
        return self.settings.alignment

    def _hide(self, state: State = State.HIDDEN) -> None:
        if self.relocating:
            self._leave_relocate()
        self.scene.hide()
        self.state = state
        self.target = None
        self.frame = None
        self.groups = []
        self.caps = None
        self.hover_handle = None
        self.disarm_operation()
        self.points = []
        self.scene.clear_edit_points()
        self._emit_target_changed()

    @property
    def visible(self) -> bool:
        """Манипулятор показан (в том числе при наведении и перетаскивании)."""
        return self.state in (State.SHOWN, State.HOVER, State.DRAGGING, State.NUMERIC)

    def shown_handles(self) -> frozenset[HandleKind]:
        """Типы ручек адаптеров за вычетом выключенных пользователем групп (15.4)."""
        if self.caps is None:
            return frozenset()
        return self.caps.handles & (self.settings.shown_kinds | {HandleKind.MOVE_FREE})

    def degenerate_handles(self, view_dir: Vector | None = None) -> set[HandleId]:
        """Ручки, скрытые по 10.8 для взгляда ``view_dir`` (умолчание — активный вид)."""
        if self.frame is None:
            return set()
        if view_dir is None:
            view_dir = self.env.view_direction()
        hidden: set[HandleId] = set()
        for axis in range(3):
            direction = self.frame.axis(axis)
            if axmath.degenerate_axis(direction, view_dir, self.settings.degenerate_angle_deg):
                for kind in (HandleKind.MOVE_AXIS, HandleKind.SCALE_AXIS, HandleKind.EXTRUDE):
                    hidden.add(HandleId(kind, axis))
            if axmath.degenerate_plane(direction, view_dir, self.settings.degenerate_angle_deg):
                hidden.add(HandleId(HandleKind.MOVE_PLANE, axis))
        # Move 2D — только у плоскости, больше всего обращённой к экрану (8.1, как в Rhino)
        normals = [self.frame.axis(axis) for axis in range(3)]
        facing = axmath.facing_plane(normals, view_dir, self.caps.axes if self.caps else None)
        for axis in range(3):
            if axis != facing:
                hidden.add(HandleId(HandleKind.MOVE_PLANE, axis))
        return hidden

    # ------------------------------------------------------------------ перенос начала (9.4, 12.4)

    @staticmethod
    def _memory_key(target: Target) -> tuple[tuple[str, ...], ...]:
        return tuple(item.obj_path for item in target.items)

    def remembered_frame(self, target: Target) -> Frame | None:
        """Перенесённая рамка для цели: хранится относительно глобального положения активного."""
        relative = self.relocated.get(self._memory_key(target))
        if relative is None:
            return None
        absolute = App.Placement(target.active.global_matrix) * relative
        return Frame(absolute.Base, absolute.Rotation, self.settings.alignment, True)

    def remember_frame(self, target: Target, frame: Frame) -> None:
        """Запомнить рамку для цели относительно активного элемента (12.4)."""
        base = App.Placement(target.active.global_matrix)
        self.relocated[self._memory_key(target)] = base.inverse() * App.Placement(
            frame.origin, frame.rotation
        )

    def start_relocate(self) -> bool:
        """Войти в режим переноса: ручки двигают рамку, а не объект."""
        if not self.visible or self.session is not None or self.frame is None:
            return False
        self.relocating = True
        self._relocate_backup = self.frame
        self.scene.set_relocating(True)
        self.env.status(tr("Axel: relocating the frame. Enter — done, Esc — cancel"))
        return True

    def finish_relocate(self) -> None:
        """Enter: запомнить новую рамку для цели."""
        if not self.relocating or self.target is None or self.frame is None:
            return
        self.remember_frame(self.target, self.frame)
        self._leave_relocate()

    def cancel_relocate(self) -> None:
        """Esc: вернуть рамку, бывшую до входа в режим."""
        if not self.relocating:
            return
        if self._relocate_backup is not None:
            self.frame = self._relocate_backup
            self.scene.set_frame(self.frame)
        self._leave_relocate()

    def _leave_relocate(self) -> None:
        self.relocating = False
        self._relocate_backup = None
        self._relocate_base = None
        self.scene.set_relocating(False)
        self.env.status("")

    def reset_frame(self) -> None:
        """Команда «Сбросить положение»: рамка по умолчанию, память для цели очищается."""
        if self.relocating:
            self.cancel_relocate()
        if self.target is not None:
            self.relocated.pop(self._memory_key(self.target), None)
        self.refresh()

    def _apply_relocate_intent(self, intent: Intent) -> None:
        base = self._relocate_base or self.frame
        if intent.operation is Operation.TRANSLATE:
            new = Frame(base.origin + intent.translation, base.rotation, base.alignment, True)
        elif intent.operation is Operation.ROTATE and intent.axis is not None:
            rot = axmath.rotation_from_axis_angle(intent.axis, intent.angle) * base.rotation
            new = Frame(base.origin, rot, base.alignment, True)
        else:
            return
        self.frame = new
        self.scene.set_frame(new)

    # ------------------------------------------------------------------ события окружения

    def on_selection_changed(self) -> None:
        """Наблюдатель выделения (13.2): цель перестраивается, взведённые операции снимаются.

        Выделение, которое команда сделала в том же цикле событий, что создала объекты
        (Draft после `make_wire` и др.), при ``DeselectNewObjects`` снимается: после создания
        ничего не выделено, как у Part, и манипулятор ждёт выделения самим пользователем.
        """
        auto, self._auto_selected = self._auto_selected, set()
        self.disarm_operation()
        if auto and self.settings.deselect_new_objects and self.session is None:
            doc = self.env.active_document()
            if doc is not None:
                selected = {name for name, _ in self.env.selection(doc.Name)}
                if selected and selected <= auto:
                    self.env.select(doc.Name, [])
                    self._hide()
                    return
        self.refresh()

    def on_object_created(self, name: str) -> None:
        """Наблюдатель документа: объект создан; забывается в конце цикла событий."""
        self._created.add(name)

    def on_selection_event(self, name: str) -> None:
        """Синхронное событие выделения одного объекта — ещё до слияния серии (13.2)."""
        if name in self._created:
            self._auto_selected.add(name)

    def end_event_cycle(self) -> None:
        """Конец цикла событий после создания: созданные объекты больше не «новые»."""
        self._created.clear()

    def on_suppression_changed(self) -> None:
        """Вход/выход из правки, диалог, команда Draft (13.3): перестроить по условиям."""
        self.refresh()

    def on_camera_changed(self) -> None:
        """Пересчёт вырожденности (10.8); оси «по виду» едут за камерой (12.2)."""
        if (
            self.visible
            and self.session is None
            and not self.relocating
            and self.settings.alignment is Alignment.VIEW
            and self.target is not None
        ):
            self.frame = self.remembered_frame(self.target) or self.default_frame(self.target)
            self.scene.set_frame(self.frame)
        if self.visible and self.caps is not None and self.session is None:
            self.scene.set_available(self.shown_handles(), self.caps.axes)
            self.scene.set_hidden_per_view(self.degenerate_handles)

    def on_objects_changed(self, names: set[str]) -> None:
        """Наблюдатель документа: изменилось положение объектов цели вне сессии — новая рамка."""
        if self.session is not None or self.target is None:
            return
        if names & {item.obj_name for item in self.target.items}:
            self.refresh()

    def on_objects_deleted(self, names: set[str]) -> None:
        """Удалён объект цели: во время сессии — отмена (11.4), иначе — перестроение."""
        if self.session is not None and names & set(self.session.changed_objects()):
            self._abort_session()
            self.env.report(tr("Axel: object deleted while dragging, session cancelled") + "\n")
        self.refresh()

    def request_menu(self, px: tuple[int, int] | None = None) -> bool:
        """Меню манипулятора (9.5): ПКМ на начале или команда; не во время сессии."""
        if not self.visible or self.session is not None or self.state is State.NUMERIC:
            return False
        self.env.show_menu(px)
        return True

    def on_hover(self, handle_id: HandleId | None) -> None:
        """Курсор над ручкой или ушёл с неё (9.1)."""
        if self.state not in (State.SHOWN, State.HOVER):
            return
        if self.caps is not None and self.caps.disabled_reason:
            return
        if handle_id == self.hover_handle:
            return
        if self.hover_handle is not None:
            self.scene.set_state(self.hover_handle, HandleStates.NORMAL)
        self.hover_handle = handle_id
        if handle_id is not None:
            self.scene.set_state(handle_id, HandleStates.HOVER)
            self.state = State.HOVER
        else:
            self.state = State.SHOWN

    # ------------------------------------------------------------------ перетаскивание

    def on_drag_start(self, handle: HandleId) -> None:
        """Нажатие на ручку: параметр захвата и открытие сессии (11.1)."""
        if (
            self.state not in (State.SHOWN, State.HOVER)
            or self.target is None
            or self.frame is None
        ):
            return
        if self.caps is None or self.caps.disabled_reason or handle.kind not in self.caps.handles:
            self._drag_cancelled = True
            return
        px = self.scene.cursor_position(handle)
        self._drag_mods = self.scene.event_modifiers(handle)
        ray = self.env.ray(px) if px is not None else None
        op_id = None if self.relocating else self._op_for_handle(handle)
        spec = self.operation(op_id) if op_id is not None else None
        if spec is not None and spec.param is not None and px is not None:
            grab: object = self._slider_grab(handle, spec, px)  # ползунок (9.2.2)
        else:
            grab = self._grab_param(handle, ray, px) if ray is not None else None
        if grab is None:
            self._drag_cancelled = True
            return
        if self.relocating:
            self._relocate_base = self.frame
            self._relocate_grab = grab
            self._theta = 0.0
            self._drag_cancelled = False
            self.state = State.DRAGGING
            self.scene.set_drag_states(handle)
            return
        session = new_session(self.target, handle, self.frame, self.groups)
        session.grab_param = grab
        session.armed_op = op_id  # операция фиксируется нажатием (9.2.1)
        self._theta = 0.0
        identity = self._identity_intent(handle, op_id, spec)
        self._begin_proxy(identity)
        self._last_recompute_ms = float("-inf")  # первое движение пересчитывается
        try:
            session.open(identity)
        except Exception as exc:  # noqa: BLE001 — принцип 5.1.6
            self.env.report(tr("Axel: could not open the session: {}").format(repr(exc)) + "\n")
            self._drag_cancelled = True
            return
        self.session = session
        self._drag_cancelled = False
        self.state = State.DRAGGING
        self.scene.set_drag_states(handle)
        self.events.drag_started.emit(self.target, identity)
        active = self.target.active
        if active.moves_other_object:
            self.env.status(tr("Axel: moving {}").format(active.object().Label))

    def on_drag_motion(self, handle: HandleId, keep_modifiers: bool = False) -> None:
        """Движение с нажатой кнопкой: намерение от начала сессии и предпросмотр (11.2)."""
        if not keep_modifiers:
            self._drag_mods = self.scene.event_modifiers(handle)
        if self.state is State.NUMERIC:
            return  # направление зафиксировано, ждём Enter/Esc (F-12)
        if self.relocating and self.state is State.DRAGGING:
            px = self.scene.cursor_position(handle)
            ray = self.env.ray(px) if px is not None else None
            if ray is None or self._relocate_base is None:
                return
            intent = self._intent(handle, ray, self._relocate_base, self._relocate_grab, px)
            if intent is not None:
                self._apply_relocate_intent(intent)
            return
        session = self.session
        if session is None or session.handle != handle:
            return
        px = self.scene.cursor_position(handle)
        ray = self.env.ray(px) if px is not None else None
        if ray is None:
            return
        if isinstance(session.grab_param, SliderGrab):
            intent = self._slider_intent(handle, session.frame, session.grab_param, px)
        else:
            intent = self._intent(handle, ray, px=px)
        if intent is None:
            return
        intent = _with_operation(intent, session.armed_op)
        if session.target.point_id is not None:
            intent = replace(intent, point_id=session.target.point_id)
        self._follow_drag(session, intent)
        if self._proxy:
            session.last_intent = intent  # документ не трогаем, двигается каркас (11.2)
            self.scene.move_proxy(intent.matrix())
            self._update_hud(session, intent)
            return
        try:
            session.preview(intent)
        except Exception as exc:  # noqa: BLE001
            self.env.report(
                tr("Axel: preview failed, the session was cancelled: {}").format(repr(exc)) + "\n"
            )
            self._abort_session()
            self.refresh()
            return
        self._recompute_during_drag(session)
        self._update_hud(session, intent)

    def on_drag_finish(self, handle: HandleId) -> None:
        """Отпускание кнопки: фиксация (11.3) или тихая отмена, если ничего не изменилось."""
        if self._drag_cancelled:
            self._drag_cancelled = False
            return
        if self.state is State.NUMERIC:
            return  # отпускание кнопки после начала ввода цифрами
        if self.relocating and self.state is State.DRAGGING:
            self.state = State.SHOWN
            self._relocate_base = None
            self.scene.set_all_states(HandleStates.NORMAL)
            return
        session = self.session
        if session is None or session.handle != handle:
            return
        intent = session.last_intent
        doc = self.env.active_document()
        self.scene.clear_hud()
        is_click = intent is None or intent.is_identity()
        if isinstance(session.grab_param, SliderGrab):
            px = self.scene.cursor_position(handle)  # ползунок: щелчок без сдвига — поле ввода
            is_click = px is None or px == session.grab_param.px
        if is_click:
            session.cancel()
            self.session = None
            if handle.kind in NUMERIC_KINDS:
                self._request_numeric(handle, "", 1.0)  # щелчок без сдвига (F-11)
                return
        else:
            try:
                if self._proxy:
                    session.preview(intent)  # применяем один раз при фиксации (11.2)
                changed = session.commit(intent)
            except Exception as exc:  # noqa: BLE001
                self.env.report(
                    tr("Axel: commit failed, the session was cancelled: {}").format(repr(exc))
                    + "\n"
                )
                changed = []
            self.session = None
            self._after_commit(session, intent, changed, doc)
        self.disarm_operation()
        self._end_proxy()
        self.state = State.SHOWN
        self.refresh()

    def _after_commit(
        self, session: DragSession, intent: Intent, changed: list[str], doc: App.Document | None
    ) -> None:
        """Общее завершение фиксации: пересчёт, выделение копии, точка после EE, автосброс."""
        if changed and doc is not None:
            self.env.recompute(doc, changed)
        self.events.drag_committed.emit(self.target, intent, list(changed))
        if intent.copy and changed and doc is not None:
            self.env.select(doc.Name, changed)  # выделяется копия (решение 11)
            self._auto_selected.clear()  # своё выделение копий не снимать (13.2)
        elif doc is not None and session.select_objects():
            self.env.select(doc.Name, session.select_objects())  # созданное операцией (7.8)
            self._auto_selected.clear()
        select_point = session.select_point()
        if select_point is not None and self.target is not None:
            self.target = replace(self.target, point_id=select_point)  # новая вершина (7.8)
        if self.settings.auto_reset and self.target is not None:
            self.relocated.pop(self._memory_key(self.target), None)

    def on_escape(self) -> bool:
        """Esc во время перетаскивания — отмена с откатом (11.4).

        Возвращает ``True``, если сессия была открыта.
        """
        if self.state is State.NUMERIC:
            self._numeric_cancel()
            return True
        if self.session is None:
            if self.relocating:
                self._drag_cancelled = self.state is State.DRAGGING
                self.cancel_relocate()
                self.state = State.SHOWN
                return True
            if self.armed_op is not None:  # Esc снимает взведённую операцию (9.2.1)
                self.disarm_operation()
                self.env.status(tr("Axel: operation cleared"))
                return True
            return self.clear_point()  # Esc возвращает манипулятор к объекту (7.10)
        self._abort_session()
        self._drag_cancelled = True  # предстоящее finish-событие драггера игнорируется
        self.disarm_operation()  # операция действует на одно перетаскивание (9.2.1)
        self.state = State.SHOWN
        self.refresh()
        return True

    def _follow_drag(self, session: DragSession, intent: Intent) -> None:
        """Манипулятор во время перетаскивания движется вместе с объектом (11.2).

        Математика намерения считается от ``session.frame``, поэтому сцене передаётся
        отдельная рамка: начало — под матрицей ``D`` намерения, оси поворачиваются вместе
        с объектом только при выравнивании по объекту (после фиксации рамка перестроится
        так же). Выдавливание и параметры матрицы не имеют — манипулятор на месте.
        """
        if intent.operation not in (Operation.TRANSLATE, Operation.ROTATE, Operation.SCALE):
            return
        frame = session.frame
        origin = intent.matrix().multVec(frame.origin)
        rotation = frame.rotation
        if (
            intent.operation is Operation.ROTATE
            and intent.axis is not None
            and frame.alignment is Alignment.OBJECT
        ):
            rotation = axmath.rotation_from_axis_angle(intent.axis, intent.angle).multiply(
                frame.rotation
            )
        self.scene.set_frame(Frame(origin, rotation, frame.alignment, frame.relocated))

    def _update_hud(self, session: DragSession, intent: Intent) -> None:
        """Направляющие и подпись (8.4); ошибка HUD не должна прерывать перетаскивание."""
        try:
            self._update_hud_unsafe(session, intent)
        except Exception as exc:  # noqa: BLE001 — принцип 5.1.6
            import traceback

            self.env.report(
                tr("Axel: HUD update failed: {}").format(repr(exc)) + "\n" + traceback.format_exc()
            )

    def _update_hud_unsafe(self, session: DragSession, intent: Intent) -> None:
        active = self.target.active if self.target is not None else None
        prefix = active.object().Label if active is not None and active.moves_other_object else ""
        wpp = self.env.world_per_pixel(session.frame.origin)
        grab = session.grab_param if isinstance(session.grab_param, Vector) else None
        radius = (grab - session.frame.origin).Length if grab is not None else 1.0
        origin_now = None
        if intent.operation is Operation.TRANSLATE:
            origin_now = session.frame.origin + intent.translation
        param_title = ""
        if isinstance(session.grab_param, SliderGrab) and session.grab_param.spec.param:
            param_title = tr(session.grab_param.spec.param.title)
        elif intent.operation is Operation.PARAMETER and session.armed_op:
            spec = self.operation(session.armed_op)
            param_title = tr(spec.param.title) if spec and spec.param else ""
        self.scene.update_hud(
            intent,
            session.frame,
            prefix=prefix,
            extent=wpp * 4000.0,
            radius=radius,
            origin_now=origin_now,
            grab_point=grab,
            param_title=param_title,
            markers=session.markers(),
        )

    def _abort_session(self) -> None:
        self.scene.clear_hud()
        self._end_proxy()
        if self.session is not None:
            self.session.cancel()
            self.session = None
            self.events.drag_cancelled.emit(self.target)

    # ------------------------------------------------------------------ числовой ввод (9.3)

    def on_key_text(self, text: str) -> bool:
        """Цифра, «−» или «=» во время перетаскивания: поле ввода с этим символом (F-12).

        Направление фиксируется по текущему положению курсора относительно точки захвата;
        сессия остаётся открытой до Enter или Esc. Возвращает, поглощена ли клавиша.
        """
        if self.state is not State.DRAGGING or self.session is None or text not in NUMERIC_KEYS:
            return False
        handle = self.session.handle
        slider = isinstance(self.session.grab_param, SliderGrab)
        if handle.kind not in DRAG_NUMERIC_KINDS and not slider:
            return False
        sign = self._current_sign(handle)
        initial = "" if text in "=" else text
        self._request_numeric(handle, initial, sign)
        return True

    def _current_sign(self, handle: HandleId) -> float:
        intent = self.session.last_intent if self.session else None
        if intent is None:
            return 1.0
        if intent.operation is Operation.ROTATE:
            return -1.0 if intent.angle < 0 else 1.0
        if intent.operation is Operation.EXTRUDE:
            return -1.0 if intent.distance < 0 else 1.0
        if handle.kind is HandleKind.MOVE_AXIS and intent.operation is Operation.TRANSLATE:
            axis = self.session.frame.axis(handle.axis)
            return -1.0 if intent.translation.dot(axis) < 0 else 1.0
        return 1.0

    def _numeric_kind(self, handle: HandleId) -> str:
        """Вид величины поля: у ползунка — число, иначе по ручке (9.3)."""
        spec = self.operation(self._op_for_handle(handle) or "")
        if spec is not None and spec.param is not None:
            return NUMBER_KIND
        return DRAG_NUMERIC_KINDS.get(handle.kind, "length")

    def _request_numeric(self, handle: HandleId, initial: str, sign: float) -> None:
        self._numeric = {"handle": handle, "sign": sign}
        self.state = State.NUMERIC
        px = self.scene.cursor_position(handle)
        self.env.show_numeric(
            self._numeric_kind(handle), initial, px, self._numeric_accept, self._numeric_cancel
        )

    def _numeric_accept(self, value: float) -> None:
        """Enter: намерение из числа, фиксация одной транзакцией."""
        info = self._numeric
        self._numeric = None
        self.scene.clear_hud()  # направляющие перетаскивания, если поле открыто цифрой (F-12)
        if info is None or self.target is None or self.frame is None:
            self.state = State.SHOWN
            return
        handle, sign = info["handle"], info["sign"]
        session = self.session
        base_frame = session.frame if session is not None else self.frame
        op_id = session.armed_op if session is not None else self._op_for_handle(handle)
        spec = self.operation(op_id) if op_id is not None else None
        intent = self._numeric_intent(handle, base_frame, value * sign, spec)
        if intent is None:
            if session is not None:
                self._abort_session()
            self.state = State.SHOWN
            self.refresh()
            return
        try:
            if session is None:
                session = new_session(self.target, handle, base_frame, self.groups)
                session.armed_op = op_id
                session.open(self._identity_intent(handle, op_id, spec))
                self.session = session
                self.events.drag_started.emit(self.target, session.last_intent)
            intent = _with_operation(intent, session.armed_op)
            session.preview(intent)
            changed = session.commit(intent)
        except Exception as exc:  # noqa: BLE001
            self.env.report(
                tr("Axel: numeric input failed, the session was cancelled: {}").format(repr(exc))
                + "\n"
            )
            self._abort_session()
            changed = []
        self.session = None
        self._after_commit(session, intent, changed, self.env.active_document())
        self.disarm_operation()
        self.state = State.SHOWN
        self.refresh()

    def _numeric_cancel(self) -> None:
        """Esc или потеря фокуса: откат, если сессия была открыта."""
        self._numeric = None
        self.env.hide_numeric()
        self._abort_session()
        self._drag_cancelled = False
        self.state = State.SHOWN
        self.refresh()

    def _numeric_intent(
        self, handle: HandleId, frame: Frame, value: float, spec: OperationSpec | None = None
    ) -> Intent | None:
        kind = handle.kind
        if spec is not None and spec.param is not None:  # ползунок: точное значение (9.2.2)
            return Intent(
                Operation.PARAMETER,
                handle,
                frame,
                op_id=spec.id,
                value=axmath.clamp_param(value, spec.param),
                source=Source.NUMERIC,
            )
        if kind is HandleKind.SCALE_AXIS:
            if value <= 0.0 and not self.settings.allow_mirror:
                self.env.status(tr("Axel: negative scale is not allowed (AllowMirror)"))
                return None
            if value == 0.0:
                return None
            factors = [1.0, 1.0, 1.0]
            factors[handle.axis] = value
            return Intent(
                Operation.SCALE,
                handle,
                frame,
                center=frame.origin,
                factors=tuple(factors),  # type: ignore[arg-type]
                source=Source.NUMERIC,
            )
        if kind is HandleKind.EXTRUDE:
            return Intent(
                Operation.EXTRUDE,
                handle,
                frame,
                axis=frame.axis(handle.axis),
                distance=value,
                both_sides=self.settings.mod_shape in self.modifiers(),
                source=Source.NUMERIC,
            )
        if kind is HandleKind.MOVE_AXIS:
            return Intent(
                Operation.TRANSLATE,
                handle,
                frame,
                translation=frame.axis(handle.axis) * value,
                source=Source.NUMERIC,
            )
        if kind is HandleKind.MOVE_PLANE and self.session is not None:
            last = self.session.last_intent
            direction = last.translation if last is not None else Vector(0, 0, 0)
            if direction.Length == 0.0:
                return None
            return Intent(
                Operation.TRANSLATE,
                handle,
                frame,
                translation=direction.normalize() * abs(value),
                source=Source.NUMERIC,
            )
        if kind is HandleKind.ROTATE:
            return Intent(
                Operation.ROTATE,
                handle,
                frame,
                axis=frame.axis(handle.axis),
                angle=_m.radians(value),
                center=frame.origin,
                source=Source.NUMERIC,
            )
        return None

    # ------------------------------------------------------------------ математика намерения

    def _op_for_handle(self, handle: HandleId) -> str | None:
        """Взведённая операция, если она действует на эту ручку (9.2.1)."""
        if self.armed_op is None:
            return None
        spec = self.operation(self.armed_op)
        return self.armed_op if spec is not None and handle.kind in spec.handles else None

    def _identity_intent(
        self, handle: HandleId, op_id: str | None = None, spec: OperationSpec | None = None
    ) -> Intent:
        """Нулевое намерение на открытие сессии: вид операции по ручке и модификатору."""
        if spec is not None and spec.param is not None:
            op = Operation.PARAMETER  # ползунок: значение появится с первым движением
        else:
            op = self._operation_for(handle)
        axis = None
        if handle.kind in (HandleKind.ROTATE, HandleKind.EXTRUDE, HandleKind.SCALE_AXIS):
            axis = self.frame.axis(handle.axis)
        return Intent(
            op,
            handle,
            self.frame,
            axis=axis,
            center=self.frame.origin,
            copy=op_id == "copy",
            op_id=None if op_id == "copy" else op_id,
            point_id=self.target.point_id if self.target is not None else None,
        )

    def _shape_modifier(self) -> bool:
        """Нажат модификатор геометрического уточнения (Shift по умолчанию, 9.2)."""
        return self.settings.mod_shape in self.modifiers()

    def _plane_scales(self) -> bool:
        """Shift на Move 2D — масштаб в двух осях, если адаптер умеет масштаб (F-06)."""
        return (
            self._shape_modifier()
            and self.caps is not None
            and HandleKind.SCALE_AXIS in self.caps.handles
        )

    def _operation_for(self, handle: HandleId) -> Operation:
        kind = handle.kind
        if kind is HandleKind.ROTATE:
            return Operation.ROTATE
        if kind is HandleKind.SCALE_AXIS:
            return Operation.SCALE
        if kind is HandleKind.EXTRUDE:
            return Operation.EXTRUDE
        if kind is HandleKind.MOVE_PLANE and self._plane_scales():
            return Operation.SCALE
        return Operation.TRANSLATE

    def _grab_param(
        self, handle: HandleId, ray: tuple[Vector, Vector], px: tuple[int, int] | None = None
    ) -> object | None:
        """``t₀`` / ``X₀`` в момент нажатия (11.1, п. 4); ``None`` — ручка вырождена."""
        p, r = ray
        frame = self.frame
        kind = handle.kind
        if kind is HandleKind.ROTATE and px is not None:
            axis = frame.axis(handle.axis)
            if axmath.ring_edge_on(axis, self.env.view_direction(), self._min_sin()):
                return self._screen_grab(frame, axis, ray, px)
        if kind is HandleKind.MOVE_AXIS:
            return axmath.ray_axis_param(frame.origin, frame.axis(handle.axis), p, r)
        if kind is HandleKind.MOVE_PLANE:
            return axmath.ray_plane_point(
                frame.origin, frame.axis(handle.axis), p, r, self._min_sin()
            )
        if kind is HandleKind.MOVE_FREE:
            return axmath.ray_plane_point(frame.origin, self.env.view_direction(), p, r, 0.0)
        if kind is HandleKind.ROTATE:
            return axmath.ray_plane_point(frame.origin, frame.axis(handle.axis), p, r, 0.0)
        if kind in (HandleKind.SCALE_AXIS, HandleKind.EXTRUDE):
            t0 = axmath.ray_axis_param(frame.origin, frame.axis(handle.axis), p, r)
            if kind is HandleKind.SCALE_AXIS and t0 is not None and abs(t0) < 1e-9:
                return None  # захват в начале: коэффициент не определён (10.6)
            return t0
        return None

    def _slider_grab(
        self, handle: HandleId, spec: OperationSpec, px: tuple[int, int]
    ) -> SliderGrab:
        """Захват ползунка: экранное направление ручки в пикселях (10.13)."""
        direction = None
        if handle.axis is not None and handle.kind in (
            HandleKind.MOVE_AXIS,
            HandleKind.SCALE_AXIS,
            HandleKind.EXTRUDE,
        ):
            axis = self.frame.axis(handle.axis)
            right, up = self.env.screen_basis()
            d = (axis.dot(right), axis.dot(up))
            if _m.hypot(*d) >= self._min_sin():
                direction = d  # иначе ручка вырождена — вертикаль экрана
        return SliderGrab(px, direction, spec)

    def _slider_intent(
        self, handle: HandleId, frame: Frame, grab: SliderGrab, px: tuple[int, int]
    ) -> Intent:
        """Значение ползунка по экранному смещению от точки нажатия (10.13)."""
        param = grab.spec.param
        value = axmath.slider_value(
            (px[0] - grab.px[0], px[1] - grab.px[1]),
            grab.direction_px,
            param.default,
            param.minimum,
            param.maximum,
            step_px=self.settings.slider_step_px,
            is_int=param.kind is int,
            float_step=param.step,
        )
        return Intent(Operation.PARAMETER, handle, frame, op_id=grab.spec.id, value=value)

    def _screen_grab(
        self, frame: Frame, axis: Vector, ray: tuple[Vector, Vector], px: tuple[int, int]
    ) -> ScreenGrab | None:
        """Экранный режим (10.5): кольцо с ребра — линия через ``O`` поперёк оси и взгляда.

        Точка захвата берётся на ближней к камере половине кольца; касательная к кольцу в ней
        проецируется на экран. На концах линии проекция касательной нулевая — угол там не растёт.
        """
        p, r = ray
        vd = self.env.view_direction()
        e = axis.cross(vd)
        if e.Length < 1e-9:
            return None
        e.normalize()
        foot = p + r * ((frame.origin - p).dot(r))  # ближайшая к O точка луча
        wpp = self.env.world_per_pixel(frame.origin)
        radius_px = self.settings.ring_radius_px
        s_px = (foot - frame.origin).dot(e) / wpp if wpp > 0 else 0.0
        s_px = max(-radius_px, min(radius_px, s_px))
        h_px = _m.sqrt(max(0.0, radius_px * radius_px - s_px * s_px))
        radial = e * s_px - vd * h_px  # ближняя половина кольца, в пикселях
        tangent = axis.cross(radial)
        right, up = self.env.screen_basis()
        return ScreenGrab(px, (tangent.dot(right), tangent.dot(up)), radius_px)

    def _intent(
        self,
        handle: HandleId,
        ray: tuple[Vector, Vector],
        frame: Frame | None = None,
        grab: object = None,
        px: tuple[int, int] | None = None,
    ) -> Intent | None:
        """Полное намерение от начала сессии по текущему лучу (10.2–10.5, 10.10, 10.11)."""
        p, r = ray
        if frame is None:
            frame = self.session.frame
            grab = self.session.grab_param
        k = axmath.drag_strength(self.settings.drag_strength_percent)
        step = self.step_active()
        kind = handle.kind
        if kind is HandleKind.ROTATE and isinstance(grab, ScreenGrab):
            if px is None:
                return None
            delta = (px[0] - grab.px[0], px[1] - grab.px[1])
            phi = axmath.screen_mode_angle(delta, grab.tangent_px, grab.radius_px) * k
            return self._rotate_intent(handle, frame, phi, absolute=True)
        if kind is HandleKind.MOVE_AXIS:
            t = axmath.ray_axis_param(frame.origin, frame.axis(handle.axis), p, r)
            if t is None:
                return None
            along = (t - grab) * k
            if step:
                along = axmath.apply_step(along, self.settings.move_step_mm)
            return Intent(
                Operation.TRANSLATE,
                handle,
                frame,
                translation=frame.axis(handle.axis) * along,
                step=step,
            )
        if kind in (HandleKind.MOVE_PLANE, HandleKind.MOVE_FREE):
            normal = (
                frame.axis(handle.axis)
                if kind is HandleKind.MOVE_PLANE
                else self.env.view_direction()
            )
            point = axmath.ray_plane_point(
                frame.origin,
                normal,
                p,
                r,
                self._min_sin() if kind is HandleKind.MOVE_PLANE else 0.0,
            )
            if point is None:
                return None
            if kind is HandleKind.MOVE_PLANE and self._plane_scales():
                f = axmath.scale_factor_2d(point, grab, frame.origin)  # F-06
                if f is None:
                    return None
                f = self._scale_step(1.0 + (f - 1.0) * k)
                factors = [1.0, 1.0, 1.0]
                for axis in range(3):
                    if axis != handle.axis:
                        factors[axis] = f
                return self._scale_intent(handle, frame, tuple(factors), step)
            delta = axmath.plane_translation(point, grab, k)
            if step:
                delta = self._step_vector(delta, frame)
            return Intent(
                Operation.TRANSLATE,
                handle,
                frame,
                translation=delta,
                step=step,
            )
        if kind is HandleKind.SCALE_AXIS:
            t = axmath.ray_axis_param(frame.origin, frame.axis(handle.axis), p, r)
            if t is None:
                return None
            f = axmath.scale_factor(t, grab, k, self.settings.allow_mirror)
            if f is None:
                return None
            f = self._scale_step(f)
            if self._shape_modifier():
                factors = (f, f, f)  # равномерный масштаб (F-07)
            else:
                factors = tuple(f if axis == handle.axis else 1.0 for axis in range(3))
            return self._scale_intent(handle, frame, factors, step)
        if kind is HandleKind.EXTRUDE:
            t = axmath.ray_axis_param(frame.origin, frame.axis(handle.axis), p, r)
            if t is None:
                return None
            dist = axmath.extrude_distance(t, grab, k)
            if step:
                dist = axmath.apply_step(dist, self.settings.move_step_mm)
            return Intent(
                Operation.EXTRUDE,
                handle,
                frame,
                axis=frame.axis(handle.axis),
                distance=dist,
                both_sides=self._shape_modifier(),  # F-09
                step=step,
            )
        if kind is HandleKind.ROTATE:
            axis = frame.axis(handle.axis)
            point = axmath.ray_plane_point(frame.origin, axis, p, r, 0.0)
            if point is None:
                return None
            min_radius = constants.ROTATION_CENTER_PX * self.env.world_per_pixel(frame.origin)
            phi = axmath.rotation_angle(frame.origin, axis, grab, point, min_radius)
            if phi is None:
                return None
            return self._rotate_intent(handle, frame, phi * k if k != 1.0 else phi)
        return None

    def _rotate_intent(
        self, handle: HandleId, frame: Frame, phi: float, absolute: bool = False
    ) -> Intent:
        """Намерение поворота: непрерывный угол (10.5) или уже накопленный (экранный режим), шаг."""
        if absolute:
            self._theta = phi
        else:
            self._theta = axmath.continuous_angle(self._theta, phi)
        angle = self._theta
        step = self.step_active()
        if step:
            angle = axmath.apply_step(angle, _m.radians(self.settings.angle_step_deg))
        return Intent(
            Operation.ROTATE,
            handle,
            frame,
            axis=frame.axis(handle.axis),
            angle=angle,
            center=frame.origin,
            step=step,
            source=Source.DRAG,
        )

    def _scale_step(self, f: float) -> float:
        """Шаг коэффициента (``ScaleStep``, 10.10) с тем же порогом зеркалирования (10.6)."""
        if not self.step_active():
            return f
        f = axmath.apply_step(f, self.settings.scale_step)
        if f <= 0.0 and not self.settings.allow_mirror:
            return constants.MIN_SCALE
        return f

    def _scale_intent(
        self, handle: HandleId, frame: Frame, factors: tuple[float, ...], step: bool
    ) -> Intent:
        return Intent(
            Operation.SCALE,
            handle,
            frame,
            axis=frame.axis(handle.axis) if handle.axis is not None else None,
            center=frame.origin,
            factors=factors,  # type: ignore[arg-type]
            step=step,
        )

    def _begin_proxy(self, identity: Intent) -> None:
        """Решить, двигать ли каркас вместо объектов (11.2, п. 3).

        Каркас двигается матрицей намерения, поэтому выдавливание и ползунок, у которых
        матрицы нет (6.4), предпросматриваются адаптером как есть.
        """
        threshold = self.settings.proxy_preview_threshold
        self._proxy = (
            self.target is not None
            and len(self.target) > threshold
            and identity.operation in (Operation.TRANSLATE, Operation.ROTATE, Operation.SCALE)
        )
        if not self._proxy:
            return
        box = axframe.target_bound_box(self.target)
        if box is None:
            self._proxy = False
            return
        self.scene.show_proxy(
            Vector(box.XMin, box.YMin, box.ZMin), Vector(box.XMax, box.YMax, box.ZMax)
        )

    def _end_proxy(self) -> None:
        if self._proxy:
            self._proxy = False
            self.scene.hide_proxy()

    def _recompute_during_drag(self, session: DragSession) -> None:
        """Политика ``RecomputeDuringDrag`` (11.2, п. 2)."""
        policy = self.settings.recompute_during_drag
        if policy == "Never":
            if not session.recompute_preview():
                return  # Placement обновляет представление сам
            # геометрия меняется — без пересчёта её не видно; пересчитываются только объекты
            # сессии, на каждое движение: при дросселировании форма отставала бы от курсора
            policy = "Always"
        doc = self.env.active_document()
        if doc is None:
            return
        if policy == "Throttled":
            now = self.env.now_ms()
            if now - self._last_recompute_ms < self.settings.recompute_throttle_ms:
                return
            self._last_recompute_ms = now
        self.env.recompute(doc, session.changed_objects())

    def _step_vector(self, delta: Vector, frame: Frame) -> Vector:
        """Шаг по каждой компоненте рамки (10.10)."""
        result = Vector(0, 0, 0)
        for axis in range(3):
            e = frame.axis(axis)
            result += e * axmath.apply_step(delta.dot(e), self.settings.move_step_mm)
        return result

    def _min_sin(self) -> float:
        return _m.sin(_m.radians(self.settings.degenerate_angle_deg))
