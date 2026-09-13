"""Внутренние константы ядра: пороги и пропорции (17.4).

Значения по умолчанию настроек пользователя (15.4) хранятся здесь же, чтобы модули ядра
не зависели от ``FreeCAD.ParamGet``; модуль ``gui.preferences`` читает настройки и передаёт
их в ядро явно.
"""

import math

# --- пороги математики (раздел 10)
PARALLEL_EPS = 1e-6
"""``1 − (d·r)²`` меньше этого — ось почти параллельна лучу (10.2)."""

DEGENERATE_ANGLE_DEG = 8.0
"""``DegenerateAngleDeg``: порог вырожденности ручек и плоскостей (10.8)."""

ROTATION_CENTER_PX = 5.0
"""Радиус вокруг центра поворота в пикселях, где угол неустойчив (10.5)."""

JUMP_GUARD_FACTOR = 100.0
"""Смещение за событие больше ``JUMP_GUARD_FACTOR × размер области вида`` игнорируется (10.8)."""

MIN_SCALE = 0.001
"""``MinScale``: нижняя граница коэффициента масштаба без зеркалирования (10.6)."""

# --- настройки по умолчанию (15.4)
DRAG_STRENGTH_PERCENT = 100
MOVE_STEP_MM = 10.0
ANGLE_STEP_DEG = 15.0
SCALE_STEP = 0.1
ALLOW_MIRROR = False
SLIDER_STEP_PX = 20
SIZE_PX = 80  # было 100; на 20 % меньше по замечанию пользователя
ARC_RADIUS_FRACTION = (
    0.75  # радиус дуги поворота в долях S (8.1; было 1,05 по снимкам Rhino); нужен ядру для 10.5
)
EDIT_POINT_PX = 7
TOOLTIP_DELAY_MS = 700
MOD_STEP = "ctrl"
RECOMPUTE_THROTTLE_MS = 100
PROXY_PREVIEW_THRESHOLD = 50
MOD_SHAPE = "shift"

TWO_PI = 2.0 * math.pi
