"""Упрощённый предпросмотр: каркас общих габаритов цели (11.2, п. 3).

Когда в цели больше ``ProxyPreviewThreshold`` объектов, во время перетаскивания документ не
меняется — двигается только этот каркас, а намерение применяется один раз при фиксации.
"""

from __future__ import annotations

import FreeCAD as App
from pivy import coin

Vector = App.Vector

COLOR = (1.0, 0.85, 0.1)
EDGES = (
    (0, 1),
    (1, 3),
    (3, 2),
    (2, 0),
    (4, 5),
    (5, 7),
    (7, 6),
    (6, 4),
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
)


def box_corners(minimum: Vector, maximum: Vector) -> list[tuple[float, float, float]]:
    """Восемь углов габаритного параллелепипеда в порядке битов (x, y, z)."""
    return [
        (
            maximum.x if i & 1 else minimum.x,
            maximum.y if i & 2 else minimum.y,
            maximum.z if i & 4 else minimum.z,
        )
        for i in range(8)
    ]


class ProxyBox:
    """Каркас габаритов, который двигается вместо объектов."""

    def __init__(self, parent: coin.SoSeparator) -> None:
        """Создать скрытый каркас под ``parent`` (корень манипулятора)."""
        self.switch = coin.SoSwitch()
        self.switch.setName("ax_proxy")
        self.switch.whichChild.setValue(-1)
        parent.addChild(self.switch)
        root = coin.SoSeparator()
        self.switch.addChild(root)
        self.transform = coin.SoMatrixTransform()
        root.addChild(self.transform)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(2.0)
        style.linePattern.setValue(0xF0F0)
        root.addChild(style)
        color = coin.SoBaseColor()
        color.rgb.setValue(*COLOR)
        root.addChild(color)
        self.coords = coin.SoCoordinate3()
        root.addChild(self.coords)
        self.lines = coin.SoIndexedLineSet()
        root.addChild(self.lines)

    def show(self, minimum: Vector, maximum: Vector) -> None:
        """Показать каркас габаритов в исходном положении."""
        corners = box_corners(minimum, maximum)
        self.coords.point.setValues(0, len(corners), corners)
        indices: list[int] = []
        for a, b in EDGES:
            indices.extend((a, b, -1))
        self.lines.coordIndex.setValues(0, len(indices), indices)
        self.move(App.Matrix())
        self.switch.whichChild.setValue(0)

    def move(self, matrix: App.Matrix) -> None:
        """Сдвинуть каркас глобальной матрицей намерения ``D``."""
        self.transform.matrix.setValue(coin.SbMatrix(*matrix.transposed().A))

    def hide(self) -> None:
        """Убрать каркас."""
        self.switch.whichChild.setValue(-1)

    @property
    def visible(self) -> bool:
        """Каркас показан."""
        return self.switch.whichChild.getValue() == 0
