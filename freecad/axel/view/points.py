"""Маркеры точек редактирования в сцене (7.10, 8.6).

Один ``SoMarkerSet`` на все точки: пикинг возвращает ``SoPointDetail`` с индексом точки,
поэтому число узлов не зависит от числа точек. Маркеры рисуются поверх геометрии
(``SoAnnotation`` + ``SoDepthBuffer test=False``) и пикаются сквозь неё
(``SoPickStyle SHAPE_ON_TOP``), как ручки (8.3).
"""

from __future__ import annotations

import FreeCAD as App
from pivy import coin

Vector = App.Vector

NODE_NAME = "ax_points"
NORMAL_MARKER = "CIRCLE_FILLED_7_7"
SELECTED_MARKER = "CIRCLE_FILLED_9_9"
MARKER_PX = 9  # размер маркера (пиксели устройства) — для поиска по экранному расстоянию
DEFAULT_COLOR = (0.25, 0.25, 0.25)
SELECTED_COLOR = (1.0, 0.85, 0.1)


def _marker(name: str) -> int:
    """Индекс маркера ``SoMarkerSet`` по имени с запасным вариантом."""
    return int(getattr(coin.SoMarkerSet, name, coin.SoMarkerSet.CIRCLE_FILLED_9_9))


class EditPointMarkers:
    """Маркеры точек редактирования одного вида."""

    def __init__(self, parent: coin.SoSeparator) -> None:
        """Создать скрытый узел маркеров под ``parent`` (корень манипулятора)."""
        self.switch = coin.SoSwitch()
        self.switch.setName("ax_points_switch")
        self.switch.whichChild.setValue(-1)
        parent.addChild(self.switch)
        root = coin.SoSeparator()
        self.switch.addChild(root)
        self.material = coin.SoBaseColor()
        self.material.rgb.setValue(*DEFAULT_COLOR)
        root.addChild(self.material)
        self.coords = coin.SoCoordinate3()
        root.addChild(self.coords)
        self.markers = coin.SoMarkerSet()
        self.markers.setName(NODE_NAME)
        root.addChild(self.markers)
        self.count = 0

    def set_points(self, positions: list[Vector], selected: int | None = None) -> None:
        """Показать маркеры в мировых точках; ``selected`` — индекс выделенной точки."""
        if not positions:
            self.hide()
            return
        self.count = len(positions)
        self.coords.point.setValues(0, self.count, [tuple(p) for p in positions])
        normal, chosen = _marker(NORMAL_MARKER), _marker(SELECTED_MARKER)
        indices = [chosen if i == selected else normal for i in range(self.count)]
        self.markers.markerIndex.setValues(0, self.count, indices)
        self.markers.numPoints.setValue(self.count)
        self.material.rgb.setValue(*(SELECTED_COLOR if selected is not None else DEFAULT_COLOR))
        self.switch.whichChild.setValue(0)

    def hide(self) -> None:
        """Скрыть маркеры."""
        self.count = 0
        self.markers.numPoints.setValue(0)
        self.switch.whichChild.setValue(-1)

    @property
    def visible(self) -> bool:
        """Маркеры показаны."""
        return self.switch.whichChild.getValue() == 0
