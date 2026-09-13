"""Провайдер рабочей плоскости (5.1.5, 12.2): интерфейс и реализация на Draft.

Axel обязан работать без Draft: при недоступном модуле подставляется пустой провайдер, и
выравнивание «по рабочей плоскости» ведёт себя как «по миру».
"""

from __future__ import annotations

from typing import Protocol

import FreeCAD as App

Rotation = App.Rotation


class WorkplaneProvider(Protocol):
    """Источник ориентации рабочей плоскости."""

    name: str

    def rotation(self) -> Rotation | None:
        """Поворот, столбцы которого — оси u, v и нормаль плоскости; ``None`` — нет плоскости."""


class NullWorkplaneProvider:
    """Без рабочей плоскости: режим WORKPLANE работает как WORLD."""

    name = "none"

    def rotation(self) -> Rotation | None:
        """Всегда ``None``."""
        return None


class DraftWorkplaneProvider:
    """Рабочая плоскость Draft через ``WorkingPlane.get_working_plane()`` (FreeCAD 1.x).

    Модуль импортируется лениво и только один раз; ошибка импорта — не сбой (Р-3).
    """

    name = "draft"

    def __init__(self) -> None:
        """Провайдер без загруженного Draft; загрузка при первом обращении."""
        self._module: object = None
        self._failed = False

    def _working_plane(self) -> object:
        if self._failed:
            return None
        if self._module is None:
            try:
                import WorkingPlane  # ленивый импорт Draft

                self._module = WorkingPlane
            except Exception as exc:  # noqa: BLE001 — Draft недоступен
                self._failed = True
                App.Console.PrintLog(f"Axel: рабочая плоскость Draft недоступна: {exc!r}\n")
                return None
        try:
            return self._module.get_working_plane(update=False)  # type: ignore[union-attr]
        except TypeError:
            return self._module.get_working_plane()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            App.Console.PrintLog(f"Axel: get_working_plane: {exc!r}\n")
            return None

    def rotation(self) -> Rotation | None:
        """Поворот текущей рабочей плоскости Draft или ``None``.

        Оси ``u``, ``v``, ``axis`` читаются напрямую: ``get_placement()`` в FreeCAD 1.1
        оставляет по слабой ссылке на вызов, а рамка строится на каждый показ (17.1).
        """
        plane = self._working_plane()
        if plane is None:
            return None
        try:
            return Rotation(App.Vector(plane.u), App.Vector(plane.v), App.Vector(plane.axis), "XYZ")
        except AttributeError:  # состав PlaneGui мог измениться — запасной путь (Р-3)
            try:
                return plane.get_placement().Rotation
            except Exception as exc:  # noqa: BLE001
                App.Console.PrintLog(f"Axel: рабочая плоскость: {exc!r}\n")
                return None
        except Exception as exc:  # noqa: BLE001 — внутренний API Draft мог измениться (Р-3)
            App.Console.PrintLog(f"Axel: рабочая плоскость: {exc!r}\n")
            return None


def default_provider() -> WorkplaneProvider:
    """Провайдер по умолчанию: Draft, если он есть, иначе пустой."""
    return DraftWorkplaneProvider()
