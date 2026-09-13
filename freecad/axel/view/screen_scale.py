"""Постоянный экранный размер (10.9): обёртка над узлом FreeCAD ``SoShapeScale``.

``SoShapeScale`` считает масштаб при рендере из объёма видимости и области вида в точке
узла и умножает на коэффициент плотности экрана, поэтому работает в обеих камерах, при
изменении окна и на HiDPI без датчика камеры (проверка С-3).
"""

from __future__ import annotations

from pivy import coin

SHAPE_SCALE_TYPE = "SoShapeScale"


def make_shape_scale(size_px: float, shape: coin.SoNode) -> coin.SoNode:
    """Кит ``SoShapeScale`` с частью ``shape``; единица фигуры = ``size_px`` логических пикселей."""
    kit_type = coin.SoType.fromName(SHAPE_SCALE_TYPE)
    if kit_type.isBad() or not kit_type.canCreateInstance():
        raise RuntimeError(f"тип {SHAPE_SCALE_TYPE} не зарегистрирован — FreeCADGui не загружен?")
    kit = kit_type.createInstance()
    kit.scaleFactor.setValue(float(size_px))
    kit.setPart("shape", shape)
    return kit


def set_size_px(kit: coin.SoNode, size_px: float) -> None:
    """Изменить размер единицы фигуры в пикселях (настройка ``SizePx``)."""
    kit.scaleFactor.setValue(float(size_px))
