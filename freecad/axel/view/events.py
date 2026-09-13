"""События 3D-вида и окружение для контроллера (13.2, 13.3, 10.1).

Здесь живёт всё, что зависит от ``FreeCADGui``, ``pivy`` и Qt: луч по курсору, направление
взгляда, наведение, Esc, датчик камеры, наблюдатели выделения и документа, условия
подавления. Контроллер получает готовые значения и вызовы.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin
from PySide import QtCore, QtWidgets

from ..core import frame as axframe
from ..core.controller import Controller
from ..core.intent import HandleId, HandleKind
from ..input.numeric import NumericField
from . import picking
from .cursors import HoverFeedback
from .scene import ManipulatorScene

Vector = App.Vector


MODIFIER_FLAGS = (
    ("ctrl", QtCore.Qt.ControlModifier),
    ("shift", QtCore.Qt.ShiftModifier),
    ("alt", QtCore.Qt.AltModifier),
    ("meta", QtCore.Qt.MetaModifier),
)


MODIFIER_KEYS = frozenset(
    {QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift, QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta}
)


def qt_modifiers(state: object) -> frozenset[str]:
    """Флаги модификаторов Qt → имена настроек ``ModStep``/``ModShape`` (9.2)."""
    return frozenset(name for name, flag in MODIFIER_FLAGS if state & flag)


def _same_node(a: coin.SoNode, b: coin.SoNode) -> bool:
    """Один и тот же узел Coin (pivy на каждый вызов даёт новую обёртку)."""
    return int(a.this) == int(b.this)


def coalesce(fn: Callable[[], None]) -> Callable[[], None]:
    """Слить серию вызовов в один на следующем цикле событий (``QTimer.singleShot(0)``)."""
    pending = {"scheduled": False}

    def _run() -> None:
        pending["scheduled"] = False
        fn()

    def _schedule() -> None:
        if not pending["scheduled"]:
            pending["scheduled"] = True
            QtCore.QTimer.singleShot(0, _run)

    return _schedule


# ---------------------------------------------------------------------------
# Окружение вида
# ---------------------------------------------------------------------------


class ViewEnvironment:
    """Реализация ``EnvironmentLike`` для одного 3D-вида (``Gui.View3DInventor``)."""

    def __init__(self, view: object) -> None:
        self.view = view
        self._numeric: NumericField | None = None

    # --- документ и выделение
    def active_document(self) -> App.Document | None:
        return App.ActiveDocument

    def selection(self, doc_name: str) -> list[tuple[str, str]]:
        """Полные пути выделения: ``getSelectionEx(doc, 0)`` (С-5)."""
        result: list[tuple[str, str]] = []
        for sel in Gui.Selection.getSelectionEx(doc_name, 0):
            subs = sel.SubElementNames or ("",)
            result.extend((sel.ObjectName, sub) for sub in subs)
        return result

    def select(self, doc_name: str, names: list[str]) -> None:
        """Заменить выделение (после копирования выделяется копия, решение 11)."""
        Gui.Selection.clearSelection()
        for name in names:
            Gui.Selection.addSelection(doc_name, name)

    # --- геометрия вида
    def _camera_and_region(self) -> tuple[coin.SoCamera, coin.SbViewportRegion]:
        manager = self.view.getViewer().getSoRenderManager()
        return manager.getCamera(), manager.getViewportRegion()

    def ray(self, px: tuple[int, int]) -> tuple[Vector, Vector] | None:
        """Луч через пиксель Coin ``px``: ``projectPointToLine`` объёма видимости (10.1)."""
        camera, region = self._camera_and_region()
        if camera is None:
            return None
        width, height = region.getViewportSizePixels().getValue()
        if width <= 0 or height <= 0:
            return None
        volume = camera.getViewVolume(region.getViewportAspectRatio())
        p0, p1 = volume.projectPointToLine(coin.SbVec2f(px[0] / width, px[1] / height))
        p0v = Vector(*p0.getValue())
        direction = Vector(*p1.getValue()) - p0v
        if direction.Length == 0.0:
            return None
        return p0v, direction.normalize()

    def view_direction(self) -> Vector:
        camera, _ = self._camera_and_region()
        d = camera.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        return Vector(*d.getValue()).normalize()

    def screen_basis(self) -> tuple[Vector, Vector]:
        camera, _ = self._camera_and_region()
        q = camera.orientation.getValue()
        right = Vector(*q.multVec(coin.SbVec3f(1, 0, 0)).getValue()).normalize()
        up = Vector(*q.multVec(coin.SbVec3f(0, 1, 0)).getValue()).normalize()
        return right, up

    def modifiers(self) -> frozenset[str]:
        return qt_modifiers(QtWidgets.QApplication.keyboardModifiers())

    def world_per_pixel(self, point: Vector) -> float:
        """Размер пикселя в мировых единицах в точке (10.9)."""
        camera, region = self._camera_and_region()
        height = region.getViewportSizePixels().getValue()[1]
        if camera.isOfType(coin.SoOrthographicCamera.getClassTypeId()):
            return camera.height.getValue() / height
        pos = Vector(*camera.position.getValue().getValue())
        dist = (point - pos).dot(self.view_direction())
        import math

        return 2.0 * dist * math.tan(camera.heightAngle.getValue() / 2.0) / height

    # --- подавление (13.3)
    def is_suppressed(self) -> bool:
        gdoc = Gui.ActiveDocument
        if gdoc is None:
            return True
        if gdoc.getInEdit() is not None:
            return True
        if Gui.Control.activeDialog():
            return True
        if getattr(App, "activeDraftCommand", None) is not None:
            return True
        view = gdoc.ActiveView
        return view is None or type(view).__name__ != "View3DInventorPy"

    # --- документ
    def recompute(self, doc: App.Document, names: list[str]) -> None:
        objects = [o for o in (doc.getObject(n) for n in names) if o is not None]
        try:
            doc.recompute(objects)
        except Exception as exc:  # noqa: BLE001 — ошибки пересчёта показывает FreeCAD (11.3)
            self.report(f"Axel: пересчёт: {exc!r}\n")

    def now_ms(self) -> float:
        return time.monotonic() * 1000.0

    def status(self, text: str) -> None:
        Gui.getMainWindow().statusBar().showMessage(text, 3000)

    # --- числовой ввод (9.3)
    def _numeric_field(self) -> NumericField | None:
        if self._numeric is None:
            viewer = _viewer_widget(self.view)
            if viewer is None:
                return None
            self._numeric = NumericField(viewer)
        return self._numeric

    def show_numeric(
        self,
        kind: str,
        initial: str,
        px: tuple[int, int] | None,
        on_accept: object,
        on_cancel: object,
    ) -> None:
        field = self._numeric_field()
        if field is None:
            on_cancel()
            return
        viewer = field.parent_widget
        dpr = viewer.devicePixelRatioF()
        _, height = self._camera_and_region()[1].getViewportSizePixels().getValue()
        if px is None:
            pos = QtCore.QPointF(viewer.width() / 2, viewer.height() / 2)
        else:
            pos = QtCore.QPointF(px[0] / dpr, (height - px[1]) / dpr)
        field.show(kind, initial, pos, on_accept, on_cancel)

    def hide_numeric(self) -> None:
        if self._numeric is not None and self._numeric.active:
            self._numeric.on_cancel = None
            self._numeric.cancel()

    # --- меню манипулятора (9.5)
    def show_menu(self, px: tuple[int, int] | None) -> None:
        from ..gui.menu import show_menu  # gui → runtime → view: импорт при вызове

        viewport = _viewport_widget(self.view)
        if viewport is None:
            return
        pos = None
        if px is not None:
            dpr = viewport.devicePixelRatioF()
            _, height = self._camera_and_region()[1].getViewportSizePixels().getValue()
            pos = QtCore.QPointF(px[0] / dpr, (height - px[1]) / dpr)
        show_menu(viewport, pos)

    def report(self, text: str) -> None:
        App.Console.PrintWarning(text if text.endswith("\n") else text + "\n")


# ---------------------------------------------------------------------------
# Привязка событий вида к контроллеру
# ---------------------------------------------------------------------------


class ViewBinding:
    """Подписки одного 3D-вида: драггеры, наведение, Esc, камера."""

    def __init__(
        self,
        view: object,
        scene: ManipulatorScene,
        controller: Controller,
        activate: Callable[[], None] | None = None,
    ) -> None:
        self.view = view
        self.scene = scene
        self.controller = controller
        self.activate = activate  # вид становится активным для контроллера (13.4)
        self._hover_cb = None
        self._camera_sensor: coin.SoNodeSensor | None = None
        self._camera_node: coin.SoCamera | None = None  # узел, на котором стоит датчик
        self._key_filter: _EscapeFilter | None = None
        self.feedback: HoverFeedback | None = None
        self._bound = False

    def bind(self) -> None:
        if self._bound:
            return
        c = self.controller
        self.scene.bind(self._active(c.on_drag_start), c.on_drag_motion, c.on_drag_finish)
        viewer_widget = _viewer_widget(self.view)
        if viewer_widget is not None:
            self.scene.set_label_widget(viewer_widget)
        self._hover_cb = self.view.addEventCallbackPivy(
            coin.SoLocation2Event.getClassTypeId(), self._on_location
        )
        self._attach_camera_sensor()
        viewport = _viewport_widget(self.view)
        if viewport is not None:
            self._key_filter = _EscapeFilter(c, self.scene, self.activate)
            self._key_filter.on_mouse = self._attach_camera_sensor
            viewport.installEventFilter(self._key_filter)
            self.feedback = HoverFeedback(
                viewport, c.settings.tooltip_delay_ms, c.settings.show_tooltips
            )
        self._bound = True

    def unbind(self) -> None:
        if not self._bound:
            return
        if self._hover_cb is not None:
            self.view.removeEventCallbackPivy(
                coin.SoLocation2Event.getClassTypeId(), self._hover_cb
            )
            self._hover_cb = None
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
            self._camera_sensor = None
        self._camera_node = None
        viewport = _viewport_widget(self.view)
        if viewport is not None and self._key_filter is not None:
            viewport.removeEventFilter(self._key_filter)
            self._key_filter = None
        if self.feedback is not None:
            self.feedback.clear()
            self.feedback = None
        self._bound = False

    def _on_location(self, node: coin.SoEventCallback) -> None:
        """Наведение: своя проверка ручки под курсором (9.1).

        Во время сессии не вызывается — события держит граббер драггера.
        """
        if not self.scene.visible:
            if self.feedback is not None and self.feedback.handle is not None:
                self.feedback.clear()
            return
        x, y = node.getEvent().getPosition().getValue()
        handle = picking.handle_under_cursor(self.scene, int(x), int(y))
        if handle is not None and self.activate is not None:
            self.activate()
        self.controller.on_hover(handle)
        if self.feedback is not None:
            caps = self.controller.caps
            reason = (caps.disabled_reason or "") if caps is not None else ""
            dpr = self.feedback.viewport.devicePixelRatioF()
            region = self.view.getViewer().getSoRenderManager().getViewportRegion()
            h = region.getViewportSizePixels().getValue()[1]
            self.feedback.update(handle, QtCore.QPointF(x / dpr, (h - y) / dpr), reason)

    def _attach_camera_sensor(self) -> None:
        """Датчик на текущей камере вида.

        При смене камеры (орто ↔ перспектива) FreeCAD создаёт новый узел, и датчик на старом
        перестаёт срабатывать — вырожденность (10.8) не пересчитывается. Поэтому проверка
        при каждом событии мыши в виде: узел сменился — датчик переставляется.
        """
        camera = self.view.getViewer().getSoRenderManager().getCamera()
        if camera is None:
            return
        if self._camera_node is not None and _same_node(self._camera_node, camera):
            return
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
        self._camera_sensor = coin.SoNodeSensor(self._on_camera, None)
        self._camera_sensor.attach(camera)
        self._camera_node = camera

    def _on_camera(self, *_: object) -> None:
        self.scene.on_view_changed()
        self.controller.on_camera_changed()

    def _active(self, fn: Callable[[HandleId], None]) -> Callable[[HandleId], None]:
        """Обёртка: перед обработчиком сделать этот вид активным для контроллера."""

        def call(handle: HandleId) -> None:
            if self.activate is not None:
                self.activate()
            fn(handle)

        return call


class _EscapeFilter(QtCore.QObject):
    """Клавиши и двойной щелчок на viewport.

    Esc во время перетаскивания: события клавиатуры не доходят до графа сцены (граббер).
    Enter в режиме переноса — готово. Двойной щелчок по ручке — перенос начала (9.1).
    """

    def __init__(
        self,
        controller: Controller,
        scene: ManipulatorScene | None = None,
        activate: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.activate = activate
        self._menu_press = False
        self._point_press = False
        self.controller = controller
        self.scene = scene
        self.on_mouse: Callable[[], None] | None = None  # событие мыши в виде (смена камеры)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        kind = event.type()
        if self.on_mouse is not None and kind in (
            QtCore.QEvent.MouseMove,
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.Wheel,
        ):
            self.on_mouse()
        if kind == QtCore.QEvent.ShortcutOverride:
            # Цифры 0–6 — сочетания видов FreeCAD; во время перетаскивания они наши (F-12).
            # Принятый ShortcutOverride отменяет сочетание, и клавиша приходит как KeyPress.
            from ..core.controller import NUMERIC_KEYS, State

            if self.controller.state is State.DRAGGING and event.text() in NUMERIC_KEYS:
                event.accept()
                return True
            return False
        if kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            # Ctrl/Shift во время перетаскивания: намерение пересчитывается от начала сессии (9.2)
            if event.key() in MODIFIER_KEYS:
                self.controller.on_modifiers_changed(qt_modifiers(event.modifiers()))
                return False
        if kind == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                return self.controller.on_escape()
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                if self.controller.relocating:
                    self.controller.finish_relocate()
                    return True
            text = event.text()
            if text and self.controller.on_key_text(text):
                return True
            return False
        if kind == QtCore.QEvent.MouseButtonDblClick and self.scene is not None:
            if event.button() != QtCore.Qt.LeftButton or not self.scene.visible:
                return False
            picked = self._handle_at(obj, event)
            if picked is not None:
                if self.activate is not None:
                    self.activate()
                return self.controller.start_relocate()
            return False
        if kind == QtCore.QEvent.MouseButtonPress and self.scene is not None:
            if event.button() == QtCore.Qt.LeftButton and self.scene.visible:
                return self._on_left_press(obj, event)
            # ПКМ по началу — меню манипулятора (9.2, 9.5); нажатие и отпускание поглощаются
            if event.button() != QtCore.Qt.RightButton or not self.scene.visible:
                return False
            picked = self._handle_at(obj, event)
            if picked is None or picked.kind is not HandleKind.MOVE_FREE:
                return False
            if self.activate is not None:
                self.activate()
            self._menu_press = self.controller.request_menu(self._coin_pos(obj, event))
            return self._menu_press
        if kind == QtCore.QEvent.MouseButtonRelease and self._point_press:
            if event.button() == QtCore.Qt.LeftButton:
                self._point_press = False
                return True
        if kind == QtCore.QEvent.MouseButtonRelease and self._menu_press:
            if event.button() == QtCore.Qt.RightButton:
                self._menu_press = False
                return True
        if kind == QtCore.QEvent.ContextMenu and self._menu_press:
            return True
        return False

    def _on_left_press(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """ЛКМ: щелчок по маркеру ставит манипулятор в точку, мимо — возвращает к объекту (7.10).

        Событие поглощается только над маркером и над шариком начала: щелчок по объекту
        должен дойти до выделения FreeCAD (9.1). Шарик начала не тянут (замечание
        пользователя): он часто стоит на маркере точки и перехватывал бы её выбор — поэтому
        над ним ищется маркер по экранному расстоянию, а без маркера нажатие просто
        поглощается вместе с парным отпусканием; ПКМ (меню) и двойной щелчок (перенос) — как
        раньше.
        """
        px = self._coin_pos(obj, event)
        if px is None:
            return False
        index = picking.point_under_cursor(self.scene, px[0], px[1])
        handle = picking.handle_under_cursor(self.scene, px[0], px[1])
        if index is None and handle is not None and handle.kind is HandleKind.MOVE_FREE:
            index = picking.point_near(self.scene, px[0], px[1])
        if index is not None:
            if self.activate is not None:
                self.activate()
            # отпускание тоже поглощается: иначе NavigationStyle сочтёт его щелчком по
            # пустому месту и снимет выделение (та же ловушка, что у ручек, этап 1)
            self._point_press = self.controller.select_point(index)
            return self._point_press
        if handle is not None and handle.kind is HandleKind.MOVE_FREE:
            self._point_press = True  # свободного перемещения за начало нет (9.1)
            return True
        if handle is None:
            self.controller.clear_point()  # щелчок по объекту или пустому месту (7.10, п. 3)
        return False

    def _coin_pos(self, obj: QtCore.QObject, event: QtCore.QEvent) -> tuple[int, int] | None:
        """Позиция события мыши в пикселях Coin (устройства, начало снизу слева)."""
        widget = obj if isinstance(obj, QtWidgets.QWidget) else None
        if widget is None or self.scene is None:
            return None
        dpr = widget.devicePixelRatioF()
        height = (
            self.scene.view.getViewer()
            .getSoRenderManager()
            .getViewportRegion()
            .getViewportSizePixels()
            .getValue()[1]
        )
        pos = event.position() if hasattr(event, "position") else event.localPos()
        return int(pos.x() * dpr), int(height - pos.y() * dpr)

    def _handle_at(self, obj: QtCore.QObject, event: QtCore.QEvent) -> HandleId | None:
        px = self._coin_pos(obj, event)
        if px is None:
            return None
        return picking.handle_under_cursor(self.scene, px[0], px[1])


def _viewer_widget(view: object) -> QtWidgets.QWidget | None:
    """``Gui::View3DInventorViewer`` (QGraphicsView) вида ``view`` — родитель для полей ввода."""
    try:
        return view.graphicsView()
    except Exception:  # noqa: BLE001 — старые сборки без graphicsView(): первый вьюер
        main = Gui.getMainWindow()
        for gv in main.findChildren(QtWidgets.QGraphicsView):
            if gv.metaObject().className() == "Gui::View3DInventorViewer":
                return gv
    return None


def _viewport_widget(view: object) -> QtWidgets.QWidget | None:
    """``QOpenGLWidget`` вьюера, которому принадлежит ``view``."""
    gv = _viewer_widget(view)
    return gv.viewport() if gv is not None else None


# ---------------------------------------------------------------------------
# Наблюдатели выделения и документа (13.2)
# ---------------------------------------------------------------------------


class SelectionWatcher:
    """``Gui.Selection.addObserver(obs, 0)`` с полными путями; серия событий — одно перестроение."""

    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self._refresh = coalesce(controller.on_selection_changed)
        self._active = False

    def start(self) -> None:
        if not self._active:
            Gui.Selection.addObserver(self, 0)
            self._active = True

    def stop(self) -> None:
        if self._active:
            Gui.Selection.removeObserver(self)
            self._active = False

    def addSelection(self, doc: str, obj: str, sub: str, pnt: object) -> None:
        self.controller.on_selection_event(obj)  # синхронно: до слияния серии
        self._refresh()

    def removeSelection(self, doc: str, obj: str, sub: str) -> None:
        self._refresh()

    def setSelection(self, doc: str) -> None:
        self._refresh()

    def clearSelection(self, doc: str) -> None:
        self._refresh()


class DocumentWatcher:
    """``App.addDocumentObserver``: положение объектов цели, удаление, undo/redo, документы."""

    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self._changed: set[str] = set()
        self._flush = coalesce(self._flush_changed)
        self._refresh = coalesce(controller.refresh)
        self._end_cycle = coalesce(controller.end_event_cycle)
        self._active = False

    def start(self) -> None:
        if not self._active:
            App.addDocumentObserver(self)
            self._active = True

    def stop(self) -> None:
        if self._active:
            App.removeDocumentObserver(self)
            self._active = False

    def _flush_changed(self) -> None:
        names, self._changed = self._changed, set()
        self.controller.on_objects_changed(names)

    JOINT_PROPS = frozenset({"Reference1", "Reference2", "ObjectToGround", "Suppressed"})

    def slotChangedObject(self, obj: App.DocumentObject, prop: str) -> None:
        axframe.invalidate_bbox(obj.Name)  # форма или положение изменились — кеш габаритов стар
        if prop == "Placement":
            self._changed.add(obj.Name)
            self._flush()
        elif prop in self.JOINT_PROPS:
            # сопряжение создано, изменено или заглушено — пересчитать возможности (7.7, 13.2)
            self._refresh()

    def slotCreatedObject(self, obj: App.DocumentObject) -> None:
        self.controller.on_object_created(obj.Name)
        self._end_cycle()
        self._refresh()

    def slotDeletedObject(self, obj: App.DocumentObject) -> None:
        axframe.invalidate_bbox(obj.Name)
        self.controller.on_objects_deleted({obj.Name})

    def slotUndoDocument(self, doc: App.Document) -> None:
        axframe.clear_bbox_cache()
        self._refresh()

    def slotRedoDocument(self, doc: App.Document) -> None:
        axframe.clear_bbox_cache()
        self._refresh()

    def slotActivateDocument(self, doc: App.Document) -> None:
        axframe.clear_bbox_cache()
        self._refresh()

    def slotDeletedDocument(self, doc: App.Document) -> None:
        self._refresh()


class GuiDocumentWatcher:
    """``Gui.addDocumentObserver``: вход и выход из режима правки (13.3)."""

    def __init__(self, controller: Controller) -> None:
        self._refresh = coalesce(controller.on_suppression_changed)
        self._active = False

    def start(self) -> None:
        if not self._active:
            Gui.addDocumentObserver(self)
            self._active = True

    def stop(self) -> None:
        if self._active:
            Gui.removeDocumentObserver(self)
            self._active = False

    def slotInEdit(self, vobj: object) -> None:
        self._refresh()

    def slotResetEdit(self, vobj: object) -> None:
        self._refresh()


class TaskViewWatcher(QtCore.QObject):
    """Диалог в панели задач открыт или закрыт (13.3).

    ``Gui.Control`` не сообщает об этом; следим за виджетом ``Gui::TaskView::TaskView``:
    сигнал ``taskUpdate`` и события ``ChildAdded``/``ChildRemoved`` (диалог — его потомок).
    Проверка ``Control.activeDialog()`` откладывается на следующий цикл событий.
    """

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._refresh = coalesce(controller.on_suppression_changed)
        self._view: QtWidgets.QWidget | None = None

    def start(self) -> None:
        if self._view is not None:
            return
        main = Gui.getMainWindow()
        for w in main.findChildren(QtWidgets.QWidget):
            if w.metaObject().className() == "Gui::TaskView::TaskView":
                self._view = w
                break
        if self._view is None:
            return
        self._view.installEventFilter(self)
        if hasattr(self._view, "taskUpdate"):
            self._view.taskUpdate.connect(self._refresh)

    def stop(self) -> None:
        if self._view is None:
            return
        self._view.removeEventFilter(self)
        if hasattr(self._view, "taskUpdate"):
            try:
                self._view.taskUpdate.disconnect(self._refresh)
            except (RuntimeError, TypeError):
                pass
        self._view = None

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Появление и удаление потомков панели задач — проверить условия подавления."""
        if event.type() in (QtCore.QEvent.ChildAdded, QtCore.QEvent.ChildRemoved):
            self._refresh()
        return False
