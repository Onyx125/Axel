"""Узлы Coin манипулятора в одном 3D-виде (8.3): добавление, удаление, видимость, состояние.

Структура (спецификация 8.3):

    SoSwitch  ax_switch                видимость манипулятора в этом виде
    └─ SoAnnotation  ax_root           поверх геометрии
       ├─ SoDepthBuffer test=False
       ├─ SoPickStyle SHAPE_ON_TOP    ручки первые в луч-пикинге
       ├─ SoLightModel BASE_COLOR
       └─ SoSeparator  ax_frame
          ├─ SoTransform               начало и поворот рамки
          └─ SoShapeScale  ax_scale    постоянный экранный размер
             └─ SoSeparator  ax_handles → SoSwitch ax_<kind>_<axis> → драггер

Сцена не знает о цели и намерении: контроллер задаёт рамку, набор ручек и состояния.
"""

from __future__ import annotations

from collections.abc import Callable

import FreeCAD as App
from pivy import coin
from PySide import QtCore

from ..core.frame import Frame
from ..core.intent import HandleId, HandleKind, Operation
from . import handles as axhandles
from . import hud, points, proxy, screen_scale
from .handles import HandleNode, HandleState, HandleStyle

Vector = App.Vector
DraggerCallback = Callable[[HandleId], None]
"""Обратный вызов ручки: start/motion/finish с идентификатором ручки."""


class ManipulatorScene:
    """Манипулятор в одном 3D-виде."""

    def __init__(self, view: object, style: HandleStyle | None = None) -> None:
        """``view`` — ``Gui.View3DInventor`` (объект ``ActiveView``)."""
        self.view = view
        self.style = style or HandleStyle()
        self.handles: dict[HandleId, HandleNode] = {}
        self._attached = False
        self._callbacks_bound = False

        self.switch = coin.SoSwitch()
        self.switch.setName("ax_switch")
        self.switch.whichChild.setValue(-1)

        root = coin.SoAnnotation()
        root.setName("ax_root")
        self.switch.addChild(root)

        depth = coin.SoDepthBuffer()
        depth.test.setValue(False)
        root.addChild(depth)
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.SHAPE_ON_TOP)
        root.addChild(pick)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        root.addChild(light)

        frame_sep = coin.SoSeparator()
        frame_sep.setName("ax_frame")
        root.addChild(frame_sep)
        self.transform = coin.SoTransform()
        frame_sep.addChild(self.transform)

        self.handles_root = coin.SoSeparator()
        self.handles_root.setName("ax_handles")
        for handle_id in axhandles.all_handle_ids():
            node = axhandles.build_handle(handle_id, self.style)
            self.handles[handle_id] = node
            self.handles_root.addChild(node.root)
        # ручка под курсором (или активная) рисуется ещё раз последней — поверх остальных:
        # тест глубины выключен, порядок в графе — порядок отрисовки, а менять порядок самих
        # ручек нельзя (он же приоритет пикинга). Копия непикабельна (8.2).
        overlay = coin.SoSeparator()
        overlay.setName("ax_overlay")
        unpickable = coin.SoPickStyle()
        unpickable.style.setValue(coin.SoPickStyle.UNPICKABLE)
        overlay.addChild(unpickable)
        self._overlay_body = coin.SoSeparator()
        overlay.addChild(self._overlay_body)
        self.handles_root.addChild(overlay)
        self._raised: HandleId | None = None
        self._dragging = False  # метка взведённой операции скрыта, пока идёт перетаскивание
        self.scale_kit = screen_scale.make_shape_scale(self.style.size_px, self.handles_root)
        self.scale_kit.setName("ax_scale")
        frame_sep.addChild(self.scale_kit)

        # направляющие и маркеры точек — в мировых координатах, вне экранного масштаба (8.4, 8.6)
        self.points = points.EditPointMarkers(root)
        self.proxy = proxy.ProxyBox(root)
        self.guides = hud.Guides(root)
        self.label: hud.CursorLabel | None = None
        self.armed_label: hud.CursorLabel | None = None  # метка взведённой операции (8.4)
        self._armed_text: str | None = None
        self._origin: Vector | None = None
        self._dpr = 1.0

    # ------------------------------------------------------------------ жизненный цикл

    def attach(self) -> None:
        """Добавить узлы в граф сцены вида."""
        if not self._attached:
            self.view.getSceneGraph().addChild(self.switch)
            self._attached = True

    def detach(self) -> None:
        """Убрать узлы из графа сцены вида (13.5)."""
        if self._attached:
            self.view.getSceneGraph().removeChild(self.switch)
            self._attached = False

    @property
    def attached(self) -> bool:
        """Узлы добавлены в граф вида."""
        return self._attached

    # ------------------------------------------------------------------ видимость и рамка

    def show(self) -> None:
        """Показать манипулятор в этом виде."""
        self.switch.whichChild.setValue(0)
        self._place_armed_label()

    def hide(self) -> None:
        """Скрыть манипулятор в этом виде (узлы остаются в графе)."""
        self.switch.whichChild.setValue(-1)
        if self.armed_label is not None:
            self.armed_label.hide()

    @property
    def visible(self) -> bool:
        """Манипулятор показан."""
        return self.switch.whichChild.getValue() == 0

    def set_frame(self, frame: Frame) -> None:
        """Начало и оси рамки в глобальных координатах."""
        o = frame.origin
        q = frame.rotation.Q
        self.transform.translation.setValue(o.x, o.y, o.z)
        self.transform.rotation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
        self._origin = Vector(o)
        self.on_view_changed()

    def on_view_changed(self) -> None:
        """Экранные элементы при смене камеры или рамки: метка операции (8.4), кольцо начала."""
        self._place_armed_label()
        node = self.handles.get(HandleId(HandleKind.MOVE_FREE))
        if node is None or node.orient is None:
            return
        camera = self.view.getViewer().getSoRenderManager().getCamera()
        if camera is None:
            return
        # R_local·R_frame = R_cam ⇒ R_local = R_cam·R_frame⁻¹ (Coin: a * b — сначала a, затем b)
        cam = camera.orientation.getValue()
        frame = self.transform.rotation.getValue()
        node.orient.rotation.setValue(cam * frame.inverse())

    def set_size_px(self, size_px: float) -> None:
        """Размер манипулятора ``SizePx`` в логических пикселях."""
        screen_scale.set_size_px(self.scale_kit, size_px)

    # ------------------------------------------------------------------ набор и состояние ручек

    def set_available(self, kinds: frozenset[HandleKind], axes: frozenset[int]) -> None:
        """Показать только ручки, поддержанные адаптерами (7.2): типы и оси."""
        for handle_id, node in self.handles.items():
            ok = handle_id.kind in kinds and (handle_id.axis is None or handle_id.axis in axes)
            node.set_visible(ok)

    def set_edit_points(self, positions: list[Vector], selected: int | None = None) -> None:
        """Маркеры точек редактирования цели (7.10, 8.6)."""
        self.points.set_points(positions, selected)

    def clear_edit_points(self) -> None:
        """Убрать маркеры точек."""
        self.points.hide()

    def show_proxy(self, minimum: Vector, maximum: Vector) -> None:
        """Каркас габаритов вместо объектов при упрощённом предпросмотре (11.2)."""
        self.proxy.show(minimum, maximum)

    def move_proxy(self, matrix: App.Matrix) -> None:
        """Сдвинуть каркас матрицей намерения."""
        self.proxy.move(matrix)

    def hide_proxy(self) -> None:
        """Убрать каркас."""
        self.proxy.hide()

    def view_direction(self) -> Vector:
        """Направление взгляда камеры своего вида (для вырожденности по 13.4)."""
        return App.Vector(*self.view.getViewDirection())

    def set_hidden_per_view(self, degenerate: Callable[[Vector], set[HandleId]]) -> None:
        """Скрыть ручки, вырожденные для направления взгляда этого вида (10.8, 13.4)."""
        self.set_hidden(degenerate(self.view_direction()))
        self.on_view_changed()

    def set_hidden(self, handle_ids: set[HandleId]) -> None:
        """Скрыть вырожденные ручки (10.8); вызывается после :meth:`set_available`."""
        for handle_id, node in self.handles.items():
            if handle_id in handle_ids:
                node.set_visible(False)

    def set_state(self, handle_id: HandleId, state: HandleState | str) -> None:
        """Состояние отображения одной ручки (8.2); принимает и имя состояния строкой."""
        st = _state(state)
        self.handles[handle_id].set_state(st, self.style)
        if st in (HandleState.HOVER, HandleState.ACTIVE):
            self._raise(handle_id)
        elif self._raised == handle_id:
            self._raise(None)

    def set_all_states(self, state: HandleState | str) -> None:
        """Одно состояние для всех ручек (например, NORMAL после перетаскивания)."""
        st = _state(state)
        for node in self.handles.values():
            node.set_state(st, self.style)
        self._raise(None)
        self._dragging = False
        self._place_armed_label()

    def set_drag_states(self, active: HandleId) -> None:
        """Во время перетаскивания: активная подсвечена, остальные полупрозрачны (8.2)."""
        for handle_id, node in self.handles.items():
            node.set_state(
                HandleState.ACTIVE if handle_id == active else HandleState.DIMMED, self.style
            )
        self._raise(active)
        self._dragging = True
        if self.armed_label is not None:
            self.armed_label.hide()  # во время перетаскивания подпись у курсора (8.4)

    def _raise(self, handle_id: HandleId | None) -> None:
        """Показать геометрию ручки поверх остальных (``None`` — убрать копию)."""
        if handle_id == self._raised:
            return
        self._overlay_body.removeAllChildren()
        self._raised = handle_id
        if handle_id is None:
            return
        node = self.handles[handle_id]
        if node.geometry is None:
            return
        if handle_id.axis is not None:
            orient = coin.SoMatrixTransform()
            orient.matrix.setValue(axhandles.axis_matrix(handle_id.axis))
            self._overlay_body.addChild(orient)
        self._overlay_body.addChild(node.geometry)

    # ------------------------------------------------------------------ HUD (8.4)

    def set_label_widget(self, viewer_widget: object) -> None:
        """Виджет вьюера для подписи у курсора; вызывается привязкой вида."""
        self.label = hud.CursorLabel(viewer_widget)
        self.armed_label = hud.CursorLabel(viewer_widget, "axel_armed_label")
        self._dpr = float(viewer_widget.devicePixelRatioF())

    def set_armed_label(self, text: str | None) -> None:
        """Метка взведённой операции у начала манипулятора (8.4); ``None`` — убрать."""
        self._armed_text = text
        self._place_armed_label()

    def _place_armed_label(self) -> None:
        label = self.armed_label
        if label is None:
            return
        text, origin = self._armed_text, self._origin
        if not text or origin is None or not self.visible or self._dragging:
            label.hide()  # при перетаскивании рамка едет за объектом (11.2) — метку не возвращать
            return
        try:
            px = self.view.getPointOnViewport(origin)
            region = self.view.getViewer().getSoRenderManager().getViewportRegion()
            h = region.getViewportSizePixels().getValue()[1]
        except Exception:  # noqa: BLE001 — вид закрывается
            label.hide()
            return
        label.show(text, QtCore.QPointF(px[0] / self._dpr, (h - px[1]) / self._dpr))

    def update_hud(
        self,
        intent: object,
        frame: Frame,
        prefix: str = "",
        extent: float = 1000.0,
        radius: float = 1.0,
        origin_now: Vector | None = None,
        grab_point: Vector | None = None,
        label: bool = True,
        param_title: str = "",
        markers: list[Vector] | None = None,
    ) -> None:
        """Направляющие и подпись по намерению (8.4); ``label`` — только в активном виде."""
        kind = intent.handle.kind
        op = intent.operation
        axis_kinds = (HandleKind.MOVE_AXIS, HandleKind.SCALE_AXIS, HandleKind.EXTRUDE)
        if op is Operation.TRANSLATE:
            axis = frame.axis(intent.handle.axis) if kind is HandleKind.MOVE_AXIS else None
            self.guides.show_translate(
                frame.origin,
                origin_now if origin_now is not None else frame.origin + intent.translation,
                axis,
                extent,
            )
        elif op is Operation.ROTATE and intent.axis is not None and grab_point is not None:
            self.guides.show_rotate(frame.origin, intent.axis, grab_point, intent.angle, radius)
        elif op in (Operation.SCALE, Operation.EXTRUDE) and kind in axis_kinds:
            self.guides.show_axis(frame.origin, frame.axis(intent.handle.axis), extent)
        elif op is Operation.PARAMETER:
            self.guides.show_markers(list(markers or []))
        else:
            self.guides.hide()
        if self.label is not None and not label:
            self.label.hide()
        elif self.label is not None:
            px = self.cursor_position(intent.handle)
            if px is not None:
                height = self.view.getViewer().getSoRenderManager().getViewportRegion()
                h = height.getViewportSizePixels().getValue()[1]
                pos = QtCore.QPointF(px[0] / self._dpr, (h - px[1]) / self._dpr)
                self.label.show(hud.format_label(intent, frame, prefix, param_title), pos)

    def clear_hud(self) -> None:
        """Убрать направляющие и подпись."""
        self.guides.hide()
        if self.label is not None:
            self.label.hide()

    def set_relocating(self, on: bool) -> None:
        """Режим переноса начала (9.4): штриховые линии ручек."""
        pattern = 0xF0F0 if on else 0xFFFF
        for node in self.handles.values():
            node.draw_style.linePattern.setValue(pattern)

    def reset_draggers(self) -> None:
        """Сбросить собственные сдвиги всех драггеров."""
        for node in self.handles.values():
            node.reset_dragger()

    # ------------------------------------------------------------------ события драггеров

    def bind(
        self, on_start: DraggerCallback, on_motion: DraggerCallback, on_finish: DraggerCallback
    ) -> None:
        """Подписать обратные вызовы драггеров через ``view.addDraggerCallback`` (С-7).

        В ``motion`` собственный сдвиг драггера сбрасывается до вызова обработчика, чтобы
        геометрия оставалась у рамки.
        """
        if self._callbacks_bound:
            raise RuntimeError("обратные вызовы уже подписаны")
        for handle_id, node in self.handles.items():
            self.view.addDraggerCallback(
                node.dragger, "addStartCallback", _wrap(handle_id, node, on_start, reset=False)
            )
            self.view.addDraggerCallback(
                node.dragger, "addMotionCallback", _wrap(handle_id, node, on_motion, reset=True)
            )
            self.view.addDraggerCallback(
                node.dragger,
                "addFinishCallback",
                _wrap(handle_id, node, on_finish, reset=True, mark_handled=True),
            )
        self._callbacks_bound = True

    def handle_for_node_name(self, name: str) -> HandleId | None:
        """Ручка по имени узла из пути выбора (8.3)."""
        handle_id = axhandles.parse_node_name(name)
        return handle_id if handle_id in self.handles else None

    def event_modifiers(self, handle_id: HandleId) -> frozenset[str]:
        """Модификаторы текущего события драггера (9.2); пусто, если события нет."""
        event = self.handles[handle_id].dragger.getEvent()
        if event is None:
            return frozenset()
        names = []
        if event.wasCtrlDown():
            names.append("ctrl")
        if event.wasShiftDown():
            names.append("shift")
        if event.wasAltDown():
            names.append("alt")
        return frozenset(names)

    def cursor_position(self, handle_id: HandleId) -> tuple[int, int] | None:
        """Позиция курсора текущего события драггера в пикселях Coin (устройства, снизу слева)."""
        event = self.handles[handle_id].dragger.getEvent()
        if event is None:
            return None
        x, y = event.getPosition().getValue()
        return int(x), int(y)


def _state(state: HandleState | str) -> HandleState:
    return HandleState[state] if isinstance(state, str) else state


def _wrap(
    handle_id: HandleId,
    node: HandleNode,
    callback: DraggerCallback,
    reset: bool,
    mark_handled: bool = False,
) -> Callable[[object], None]:
    def _cb(dragger: object) -> None:
        if reset:
            node.reset_dragger()
        if mark_handled:
            # Щелчок без движения: Coin не помечает отпускание обработанным, и
            # NavigationStyle FreeCAD очищает выделение. Помечаем сами (9.1: событие поглощается).
            action = dragger.getHandleEventAction()
            if action is not None:
                action.setHandled()
        callback(handle_id)

    return _cb
