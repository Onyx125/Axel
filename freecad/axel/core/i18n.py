"""Перевод строк интерфейса (15.5).

Исходный язык строк — английский, перевод на русский лежит в
``resources/translations/Axel_ru.ts`` и собирается в ``.qm``. Ресурсы команд FreeCAD
переводит сам по имени команды как контексту, поэтому там используется
``App.Qt.QT_TRANSLATE_NOOP``; все остальные строки переводятся здесь, в контексте ``Axel``.
"""

from __future__ import annotations

import FreeCAD as App

CONTEXT = "Axel"


def tr(text: str) -> str:
    """Перевести строку интерфейса в контексте ``Axel``."""
    return App.Qt.translate(CONTEXT, text)
