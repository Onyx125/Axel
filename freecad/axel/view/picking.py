"""Определение ручки под курсором (8.3): собственный луч-пикинг по графу вида.

Пикинг делается по графу ``SoRenderManager`` (в нём камера), а не по ``view.getSceneGraph()``.
Путь попадания приходит как ``SoPath``, который не заходит внутрь китов (``SoShapeScale``,
драггеры); имя ручки видно только в ``SoFullPath`` — отсюда ``coin.cast``.
"""

from __future__ import annotations

import FreeCAD as App
from pivy import coin

from ..core.intent import HandleId
from . import points as axpoints
from .scene import ManipulatorScene


def handle_in_path(scene: ManipulatorScene, path: coin.SoPath) -> HandleId | None:
    """Ручка манипулятора в пути попадания или ``None``."""
    full = coin.cast(path, "SoFullPath")
    for i in range(full.getLength() - 1, -1, -1):
        handle_id = scene.handle_for_node_name(str(full.getNode(i).getName()))
        if handle_id is not None:
            return handle_id
    return None


def point_under_cursor(scene: ManipulatorScene, x: int, y: int) -> int | None:
    """Индекс маркера точки редактирования под курсором или ``None`` (7.10).

    ``SoMarkerSet`` один на все точки: индекс приходит в ``SoPointDetail`` попадания.
    """
    if not scene.points.visible:
        return None
    viewer = scene.view.getViewer()
    manager = viewer.getSoRenderManager()
    action = coin.SoRayPickAction(manager.getViewportRegion())
    action.setPoint(coin.SbVec2s(int(x), int(y)))
    action.setRadius(viewer.getPickRadius())
    action.apply(manager.getSceneGraph())
    picked = action.getPickedPoint()
    if picked is None:
        return None
    full = coin.cast(picked.getPath(), "SoFullPath")
    if str(full.getNode(full.getLength() - 1).getName()) != axpoints.NODE_NAME:
        return None
    detail = picked.getDetail()
    if detail is None or not detail.isOfType(coin.SoPointDetail.getClassTypeId()):
        return None
    return int(coin.cast(detail, "SoPointDetail").getCoordinateIndex())


def point_near(scene: ManipulatorScene, x: int, y: int) -> int | None:
    """Индекс маркера точки в радиусе пикинга от ``(x, y)`` по экранному расстоянию.

    Нужен, когда луч-пикинг перехватывает шарик начала, стоящий на маркере (7.10, 9.1).
    """
    if not scene.points.visible:
        return None
    viewer = scene.view.getViewer()
    radius = viewer.getPickRadius() + axpoints.MARKER_PX / 2
    best, best_d = None, radius
    for i in range(scene.points.count):
        p = scene.points.coords.point.getValues()[i].getValue()
        sx, sy = scene.view.getPointOnViewport(App.Vector(*p))
        d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = i, d
    return best


def handle_under_cursor(
    scene: ManipulatorScene, x: int, y: int, radius_px: float | None = None
) -> HandleId | None:
    """Ручка под точкой ``(x, y)`` в пикселях Coin (устройства, начало внизу слева).

    Радиус пикинга по умолчанию — ``viewer.getPickRadius()`` (5 px), как у FreeCAD.
    """
    viewer = scene.view.getViewer()
    manager = viewer.getSoRenderManager()
    action = coin.SoRayPickAction(manager.getViewportRegion())
    action.setPoint(coin.SbVec2s(int(x), int(y)))
    action.setRadius(viewer.getPickRadius() if radius_px is None else radius_px)
    action.apply(manager.getSceneGraph())
    picked = action.getPickedPoint()
    if picked is None:
        return None
    return handle_in_path(scene, picked.getPath())
