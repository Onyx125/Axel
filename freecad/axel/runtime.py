"""Состояние дополнения в работающем FreeCAD: контроллер, сцена, окружение, наблюдатели.

Один экземпляр на приложение (:func:`get_runtime`). Знает о ``FreeCADGui``; создаётся из
``init_gui`` и управляется командами ``gui.commands``. Включение и выключение (13.1, 13.5):
выключенный Axel не держит ни узлов в сценах, ни наблюдателей.

Манипулятор показывается во всех 3D-видах активного документа (13.4): на каждый вид —
слот со своей сценой, окружением и привязкой. Контроллер один; его «сцена» раздаёт
вызовы всем слотам, а «окружение» отвечает за вид, в котором произошло последнее
взаимодействие (активный слот).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .adapters.assembly import AssemblyAdapter
from .adapters.attachment import AttachmentAdapter
from .adapters.draft import DraftAdapter
from .adapters.placement import PlacementAdapter
from .api import registry
from .core.controller import Controller, Settings
from .input.workplane import default_provider
from .view.events import (
    DocumentWatcher,
    GuiDocumentWatcher,
    SelectionWatcher,
    TaskViewWatcher,
    ViewBinding,
    ViewEnvironment,
)
from .view.handles import HandleStyle
from .view.scene import ManipulatorScene

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/Axel"


def params() -> App.ParameterGrp:
    """Группа параметров Axel (15.4)."""
    return App.ParamGet(PARAM_PATH)


def is_3d_view(view: object) -> bool:
    """``ActiveView`` — 3D-вид, а не таблица или чертёж."""
    return view is not None and type(view).__name__ == "View3DInventorPy"


def view_key(view: object) -> int:
    """Ключ вида: обёртки ``View3DInventorPy`` создаются заново, граф сцены — постоянный."""
    return int(view.getSceneGraph().this)


@dataclass
class ViewSlot:
    """Сцена, окружение и привязка одного 3D-вида."""

    key: int
    view: object
    scene: ManipulatorScene
    env: ViewEnvironment
    binding: ViewBinding

    def close(self) -> None:
        """Снять привязку и узлы из графа вида (вид мог быть уже закрыт FreeCAD)."""
        for step in (self.binding.unbind, self.scene.detach):
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                App.Console.PrintLog(f"Axel: слот вида уже закрыт: {exc!r}\n")


class Runtime:
    """Связка контроллера с активным 3D-видом и наблюдателями FreeCAD."""

    def __init__(self) -> None:
        """Выключенное состояние; узлы и наблюдатели создаются в :meth:`enable`."""
        self.settings = Settings()
        self.style = HandleStyle()  # перечитываются при каждом включении (gui.preferences)
        self.controller: Controller | None = None
        self.slots: dict[int, ViewSlot] = {}  # все 3D-виды активного документа (13.4)
        self.active: ViewSlot | None = None  # вид последнего взаимодействия
        self.env: _SwitchableEnvironment | None = None
        self.selection_watcher: SelectionWatcher | None = None
        self.document_watcher: DocumentWatcher | None = None
        self.gui_watcher: GuiDocumentWatcher | None = None
        self.task_watcher: TaskViewWatcher | None = None
        self.enabled = False
        self._mdi_connected = False
        self._listeners: list = []

    # ------------------------------------------------------------------ запуск (13.1)

    def start(self) -> None:
        """Регистрация стандартных адаптеров; включение по сохранённой настройке."""
        for adapter in (
            PlacementAdapter(),
            AttachmentAdapter(),
            AssemblyAdapter(),
            DraftAdapter(),
        ):
            registry.register(adapter)
        self._connect_mdi()
        from .gui import preferences

        preferences.migrate()
        preferences.install_page()
        preferences.watch(self.reload_settings)
        if params().GetBool("Enabled", True):
            self.enable()

    def _connect_mdi(self) -> None:
        if self._mdi_connected:
            return
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if mdi is not None:
            mdi.subWindowActivated.connect(self._on_subwindow)
            self._mdi_connected = True

    # ------------------------------------------------------------------ включение / выключение

    def enable(self) -> None:
        """Включить: сцена в активном виде, контроллер, наблюдатели (13.1, п. 6)."""
        if self.enabled:
            return
        self.enabled = True
        params().SetBool("Enabled", True)
        from .gui import preferences

        self.style = preferences.load_style()
        loaded = preferences.load_settings()
        for name, value in vars(loaded).items():
            setattr(self.settings, name, value)
        if self.controller is None:
            # окружение и сцена подменяются при смене вида, контроллер один
            self.env = _SwitchableEnvironment()
            self.controller = Controller(
                registry, _MultiScene(self), self.env, self.settings, workplane=default_provider()
            )
            self.controller.before_refresh = self._ensure_view
            from .gui import commands

            # операции адаптеров верстаков получают команды автоматически (15.1)
            self.controller.on_operations = commands.ensure_operation_commands
        self.selection_watcher = SelectionWatcher(self.controller)
        self.document_watcher = DocumentWatcher(self.controller)
        self.gui_watcher = GuiDocumentWatcher(self.controller)
        self.task_watcher = TaskViewWatcher(self.controller)
        for w in (
            self.selection_watcher,
            self.document_watcher,
            self.gui_watcher,
            self.task_watcher,
        ):
            w.start()
        self.controller.enable()  # refresh → _ensure_view → сцена в активном виде
        self._notify()

    def disable(self) -> None:
        """Выключить: отменить сессию, снять узлы и наблюдатели (13.5)."""
        if not self.enabled:
            return
        self.enabled = False
        params().SetBool("Enabled", False)
        if self.controller is not None:
            self.controller.disable()
        for w in (
            self.selection_watcher,
            self.document_watcher,
            self.gui_watcher,
            self.task_watcher,
        ):
            if w is not None:
                w.stop()
        self.selection_watcher = self.document_watcher = self.gui_watcher = None
        self.task_watcher = None
        self._close_slots()
        self._notify()

    def reload_settings(self) -> None:
        """Перечитать стиль и настройки из параметров (страница настроек, 15.4).

        Размеры и цвета ручек заданы при построении узлов, поэтому сцены пересоздаются.
        """
        if not self.enabled or self.controller is None:
            return
        from .gui import preferences

        style = preferences.load_style()
        loaded = preferences.load_settings()
        for name, value in vars(loaded).items():
            setattr(self.settings, name, value)
        if style != self.style:
            self.style = style
            self._close_slots()  # узлы ручек строятся по стилю — пересобрать (15.4)
        self.controller.refresh()

    def save_setting(self, name: str, value: bool) -> None:
        """Сохранить булеву настройку в параметры (15.4)."""
        params().SetBool(name, value)

    def toggle(self) -> None:
        """Переключить включённость."""
        if self.enabled:
            self.disable()
        else:
            self.enable()

    # ------------------------------------------------------------------ виды (13.4)

    @property
    def scene(self) -> ManipulatorScene | None:
        """Сцена активного вида (для проб и команд)."""
        return self.active.scene if self.active is not None else None

    @property
    def binding(self) -> ViewBinding | None:
        """Привязка активного вида."""
        return self.active.binding if self.active is not None else None

    @property
    def view(self) -> object:
        """Активный вид."""
        return self.active.view if self.active is not None else None

    def _open_slot(self, view: object) -> ViewSlot:
        key = view_key(view)
        scene = ManipulatorScene(view, self.style)
        scene.attach()
        slot = ViewSlot(key, view, scene, ViewEnvironment(view), None)  # type: ignore[arg-type]
        slot.binding = ViewBinding(view, scene, self.controller, activate=self._activator(slot))
        slot.binding.bind()
        self.slots[key] = slot
        return slot

    def _activator(self, slot: ViewSlot) -> Callable[[], None]:
        def activate() -> None:
            self._set_active(slot)

        return activate

    def _set_active(self, slot: ViewSlot | None) -> None:
        if slot is self.active:
            return
        self.active = slot
        self.env.delegate = slot.env if slot is not None else None  # type: ignore[union-attr]

    def _sync_views(self, views: list[object]) -> None:
        """Слоты ровно для ``views``: лишние закрыть, новых открыть."""
        wanted = {view_key(v): v for v in views if is_3d_view(v)}
        for key in [k for k in self.slots if k not in wanted]:
            slot = self.slots.pop(key)
            if slot is self.active:
                self._set_active(None)
            slot.close()
        for key, view in wanted.items():
            if key not in self.slots:
                self._open_slot(view)

    def _close_slots(self) -> None:
        self._sync_views([])

    def _ensure_view(self) -> None:
        """Слоты для всех 3D-видов активного документа; вызывается перед каждым refresh."""
        gdoc = Gui.ActiveDocument
        views = gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc is not None else []
        self._sync_views(views)
        if gdoc is not None and (self.active is None or self.active.key not in self.slots):
            active_view = gdoc.ActiveView
            if is_3d_view(active_view) and view_key(active_view) in self.slots:
                self._set_active(self.slots[view_key(active_view)])
            elif self.slots:
                self._set_active(next(iter(self.slots.values())))

    def _on_subwindow(self, window: object) -> None:
        if not self.enabled or self.controller is None:
            return
        if self.controller.session is not None:
            self.controller.on_escape()  # смена вида во время сессии — отмена (11.4)
        slot = self._slot_of_window(window)
        if slot is not None:
            self._set_active(slot)
        self.controller.refresh()  # → _ensure_view: слот нового подокна появляется здесь
        if slot is None:
            slot = self._slot_of_window(window)
            if slot is not None:
                self._set_active(slot)

    def _slot_of_window(self, window: object) -> ViewSlot | None:
        """Слот, чей вьюер лежит в подокне ``window``."""
        if window is None:
            return None
        widget = window.widget() if hasattr(window, "widget") else None
        if widget is None:
            return None
        for slot in self.slots.values():
            try:
                gv = slot.view.graphicsView()
            except Exception:  # noqa: BLE001
                continue
            if gv is not None and (gv is widget or widget.isAncestorOf(gv)):
                return slot
        return None

    # ------------------------------------------------------------------ слушатели состояния

    def add_listener(self, fn: object) -> None:
        """``fn(enabled: bool)`` при включении/выключении (кнопка строки состояния, команда)."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn(self.enabled)
            except Exception as exc:  # noqa: BLE001
                App.Console.PrintWarning(f"Axel: слушатель состояния: {exc!r}\n")


class _MultiScene:
    """Сцена-раздатчик: вызовы контроллера уходят во все виды документа (13.4).

    Позиция курсора, модификаторы события и подпись у курсора — только из активного вида
    (там идёт событие); остальное рассылается во все виды.
    """

    ACTIVE_ONLY = frozenset({"cursor_position", "event_modifiers"})

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    @property
    def visible(self) -> bool:
        scene = self.runtime.scene
        return bool(scene is not None and scene.visible)

    def update_hud(self, *args: object, **kwargs: object) -> None:
        active = self.runtime.active
        for slot in list(self.runtime.slots.values()):
            slot.scene.update_hud(*args, label=slot is active, **kwargs)

    def __getattr__(self, name: str) -> object:
        runtime = self.__dict__["runtime"]
        if name in self.ACTIVE_ONLY:
            scene = runtime.scene
            return getattr(scene, name) if scene is not None else _noop

        def fan_out(*args: object, **kwargs: object) -> None:
            for slot in list(runtime.slots.values()):
                getattr(slot.scene, name)(*args, **kwargs)

        return fan_out


class _SwitchableEnvironment:
    """Окружение-переходник; без вида — всё подавлено."""

    def __init__(self) -> None:
        self.delegate: ViewEnvironment | None = None

    def __getattr__(self, name: str) -> object:
        delegate = self.__dict__.get("delegate")
        if delegate is None:
            if name == "is_suppressed":
                return lambda: True
            if name == "active_document":
                return lambda: None
            return _noop
        return getattr(delegate, name)


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    """Единственный экземпляр на приложение."""
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime
