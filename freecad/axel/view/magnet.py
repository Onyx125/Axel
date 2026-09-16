"""Примагничивание курсора к ручке под ним (8.5; замечание пользователя: промахи по ручкам).

Пока курсор над ручкой, он мягко доводится до её «оси» (:func:`handles.anchor_polyline`):
у кубика масштаба и шарика выдавливания — до центра, у стрелки — до ближайшей точки
отрезка «стержень + конус», у дуги — до ближайшей точки дуги; квадрат плоскости большой и
не магнитится (``handles.MAGNETIC_KINDS``). Тянет только с ``CAPTURE_PX``. Расчёт в
экранных пикселях: точки оси переводятся в мир мировой матрицей узла ручек
(``SoGetMatrixAction`` по пути сквозь ``SoShapeScale`` — масштаб узел считает сам при
отрисовке, повторять его формулу не нужно) и проецируются ``getPointOnViewport``.

Курсор ведёт таймер: за тик — доля оставшегося расстояния, так что доводка мягкая, а
движение пользователя всегда сильнее. Ушёл с ручки — притяжение прекращается (событие
наведения приходит с ``None``). Во время перетаскивания события держит драггер, и
:meth:`CursorMagnet.update` не вызывается; на всякий случай привязка вида останавливает
таймер при начале перетаскивания.

Тянется только физический курсор: если позиция события не совпадает с ``QCursor.pos()``
(синтетические события проб), ничего не делается — иначе проба утащила бы настоящий курсор
в 3D-вид (ловушка «положение мыши», журнал).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import FreeCAD as App
from pivy import coin
from PySide import QtCore, QtGui, QtWidgets

from ..core import math as axmath
from ..core.intent import HandleId
from . import handles as axhandles
from .scene import ManipulatorScene

TICK_MS = 24
"""Период таймера доводки (было 16 — кадр; реже и мягче по замечанию пользователя)."""

MIN_STEP_PX = 1.0
"""Наименьший сдвиг за тик: позиция курсора целочисленная."""

PULL_FRACTION = 0.2
"""Доля оставшегося расстояния, на которую курсор сдвигается за тик (было 0,35 — сильно)."""

CAPTURE_PX = 4.0
"""Дальше этого от оси ручки (логические пиксели) магнит не тянет, хотя ручка под курсором.

Наведение срабатывает в радиусе пикинга (5 px устройства) от геометрии, у кубика — ещё и
по его телу; захват короче — по замечанию пользователя.
"""

SETTLE_PX = 1.0
"""Ближе этого (логические пиксели) курсор считается на месте."""

MAX_TICKS = 40
"""Страховка: не больше стольких тиков подряд (≈0,65 с) на одну доводку."""

EVENT_TOLERANCE_PX = 3.0
"""Событие дальше этого от физического курсора — синтетическое, не тянуть."""


class CursorMagnet:
    """Доводка курсора к ручке для viewport одного вида."""

    def __init__(
        self,
        scene: ManipulatorScene,
        viewport: QtWidgets.QWidget,
        enabled: Callable[[], bool],
    ) -> None:
        """Создать магнит; ``enabled`` читается на каждом наведении (настройка без перепривязки)."""
        self.scene = scene
        self.viewport = viewport
        self.enabled = enabled
        self.handle: HandleId | None = None
        self._ticks = 0
        self._timer = QtCore.QTimer()
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ вход

    def update(self, handle: HandleId | None, px: tuple[int, int]) -> None:
        """Курсор над ``handle`` (или ``None``) в точке ``px`` (пиксели Coin, снизу слева)."""
        if handle is None or handle.kind not in axhandles.MAGNETIC_KINDS or not self.enabled():
            self.stop()
            return
        pos = self._cursor_local()
        if pos is None or (pos - self._to_local(px)).manhattanLength() > EVENT_TOLERANCE_PX:
            self.stop()  # событие не от физического курсора
            return
        if handle != self.handle:
            self._ticks = 0
        self.handle = handle
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Прекратить доводку (уход с ручки, перетаскивание, скрытие, отвязка)."""
        self.handle = None
        self._timer.stop()

    @property
    def active(self) -> bool:
        """Таймер доводки идёт."""
        return self._timer.isActive()

    # ------------------------------------------------------------------ тик

    def _tick(self) -> None:
        if self.handle is None or not self.scene.visible or self._ticks >= MAX_TICKS:
            self.stop()
            return
        self._ticks += 1
        pos = self._cursor_local()
        if pos is None or not self.viewport.rect().contains(pos.toPoint()):
            self.stop()
            return
        target = self.target(self.handle, pos)
        if target is None:
            self.stop()
            return
        delta = target - pos
        dist = math.hypot(delta.x(), delta.y())
        if dist <= SETTLE_PX or dist > CAPTURE_PX:
            self.stop()  # на месте — или ещё далеко: ждать нового наведения ближе
            return
        # шаг — доля остатка, но не меньше пикселя (иначе округление съест движение)
        # и не дальше цели
        step = min(dist, max(PULL_FRACTION * dist, MIN_STEP_PX))
        new = pos + delta * (step / dist)
        QtGui.QCursor.setPos(
            self.viewport.mapToGlobal(QtCore.QPoint(round(new.x()), round(new.y())))
        )

    # ------------------------------------------------------------------ геометрия

    def target(self, handle: HandleId, pos: QtCore.QPointF) -> QtCore.QPointF | None:
        """Точка оси ручки, ближайшая к ``pos`` (логические координаты viewport)."""
        matrix = self._handles_matrix()
        if matrix is None:
            return None
        polyline: list[tuple[float, float]] = []
        for point in axhandles.anchor_polyline(handle, self.scene.style):
            world = _transform(matrix, point)
            try:
                sx, sy = self.scene.view.getPointOnViewport(world)
            except Exception:  # noqa: BLE001 — вид закрывается
                return None
            local = self._to_local((sx, sy))
            polyline.append((local.x(), local.y()))
        nearest = axmath.nearest_on_polyline((pos.x(), pos.y()), polyline)
        return None if nearest is None else QtCore.QPointF(*nearest)

    def _handles_matrix(self) -> coin.SbMatrix | None:
        return handles_matrix(self.scene)

    def _cursor_local(self) -> QtCore.QPointF | None:
        try:
            return QtCore.QPointF(self.viewport.mapFromGlobal(QtGui.QCursor.pos()))
        except RuntimeError:  # виджет удалён
            return None

    def _to_local(self, px: tuple[float, float]) -> QtCore.QPointF:
        """Пиксели Coin (устройства, снизу слева) → логические координаты viewport."""
        dpr = self.viewport.devicePixelRatioF()
        region = self.scene.view.getViewer().getSoRenderManager().getViewportRegion()
        height = region.getViewportSizePixels().getValue()[1]
        return QtCore.QPointF(px[0] / dpr, (height - px[1]) / dpr)


def handles_matrix(scene: ManipulatorScene) -> coin.SbMatrix | None:
    """Мировая матрица узла ручек: рамка × масштаб ``SoShapeScale``.

    Путь ищется от переключателя манипулятора (над ним в графе FreeCAD преобразований
    нет), с заходом внутрь китов — часть ``scale`` у ``SoShapeScale`` приватная.
    """
    search = coin.SoSearchAction()
    search.setNode(scene.handles_root)
    search.setSearchingAll(True)
    # в киты поиск заходит только при глобальном флаге SoBaseKit — включить на время
    was_searching = coin.SoBaseKit.isSearchingChildren()
    coin.SoBaseKit.setSearchingChildren(True)
    try:
        search.apply(scene.switch)
    finally:
        coin.SoBaseKit.setSearchingChildren(was_searching)
    path = search.getPath()
    if path is None:
        return None
    region = scene.view.getViewer().getSoRenderManager().getViewportRegion()
    action = coin.SoGetMatrixAction(region)
    action.apply(path)
    # getMatrix() — ссылка внутрь действия; после его сборки она висячая (мусор, NaN,
    # проба d16: якоря в (0, 0) со второго) — вернуть копию
    return coin.SbMatrix(action.getMatrix().getValue())  # 4×4 кортежи — копия значений


def size_world(scene: ManipulatorScene) -> float | None:
    """Размер S манипулятора в мировых единицах (для проб: не по габаритам — их растят тени)."""
    matrix = handles_matrix(scene)
    if matrix is None:
        return None
    return (_transform(matrix, (1.0, 0.0, 0.0)) - _transform(matrix, (0.0, 0.0, 0.0))).Length


def _transform(matrix: coin.SbMatrix, point: tuple[float, float, float]) -> App.Vector:
    """``matrix`` × точка; pivy отдаёт ``multVecMatrix`` либо возвратом, либо в аргумент."""
    src = coin.SbVec3f(*point)
    try:
        out = matrix.multVecMatrix(src)
    except TypeError:
        out = coin.SbVec3f()
        matrix.multVecMatrix(src, out)
    return App.Vector(*out.getValue())
