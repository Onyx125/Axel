"""Чтение настроек Axel из параметров FreeCAD (15.4).

Этап 1: только чтение в ``HandleStyle`` и ``Settings``; страница настроек — этап 3. Хранение:
``User parameter:BaseApp/Preferences/Mod/Axel``. Цвета — в формате FreeCAD (``0xRRGGBBAA``).
"""

from __future__ import annotations

from pathlib import Path

import FreeCAD as App

from ..core import constants
from ..core.controller import Settings
from ..core.frame import Alignment, OriginMode
from ..core.intent import HandleKind
from ..view.handles import DEFAULT_AXIS_COLORS, RGB, HandleStyle

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/Axel"


def group() -> App.ParameterGrp:
    """Группа параметров Axel."""
    return App.ParamGet(PARAM_PATH)


def rgb_to_unsigned(rgb: RGB) -> int:
    """``(r, g, b)`` в долях → ``0xRRGGBBAA`` FreeCAD."""
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb)
    return (r << 24) | (g << 16) | (b << 8) | 0xFF


def unsigned_to_rgb(value: int) -> RGB:
    """``0xRRGGBBAA`` FreeCAD → ``(r, g, b)`` в долях."""
    return (
        ((value >> 24) & 0xFF) / 255.0,
        ((value >> 16) & 0xFF) / 255.0,
        ((value >> 8) & 0xFF) / 255.0,
    )


# Порядок значений совпадает с порядком пунктов в resources/ui/Preferences.ui:
# Gui::PrefComboBox сохраняет номер пункта, поэтому перечисления читаются и как строка
# (записана вручную или прежней версией), и как индекс.
ALIGNMENT_ORDER = (Alignment.WORLD, Alignment.WORKPLANE, Alignment.OBJECT, Alignment.VIEW)
ORIGIN_ORDER = (OriginMode.BOUNDING_BOX_CENTER, OriginMode.PLACEMENT_BASE)
RECOMPUTE_ORDER = ("Never", "Throttled", "Always")
MOD_ORDER = ("ctrl", "shift", "meta")


def read_enum(key: str, order: tuple, default: object) -> object:
    """Значение перечисления из параметров: строка или номер пункта списка (15.4)."""
    g = group()
    text = g.GetString(key, "")
    if text:
        for value in order:
            name = value.value if hasattr(value, "value") else value
            if str(name).lower() == text.lower():
                return value
    index = g.GetInt(key, -1)
    if 0 <= index < len(order):
        return order[index]
    return default


COLOR_KEYS = ("ColorX", "ColorY", "ColorZ", "ColorHover", "ColorDisabled")
UNSET_BUTTON_COLOR = 0xE3E3E3FF
"""Цвет пустой ``Gui::PrefColorButton``: его записывала страница без умолчаний в форме."""


def default_colors() -> dict[str, int]:
    """Цвета по умолчанию в формате FreeCAD по ключам параметров."""
    d = HandleStyle()
    return {
        "ColorX": rgb_to_unsigned(d.axis_colors[0]),
        "ColorY": rgb_to_unsigned(d.axis_colors[1]),
        "ColorZ": rgb_to_unsigned(d.axis_colors[2]),
        "ColorHover": rgb_to_unsigned(d.hover_color),
        "ColorDisabled": rgb_to_unsigned(d.disabled_color),
    }


def repair_unset_colors() -> bool:
    """Убрать цвета, записанные прежней страницей настроек без умолчаний.

    Кнопки цветов в форме не имели свойства ``color``, поэтому первое же «OK» в диалоге
    записывало во все пять ключей серый ``0xE3E3E3FF`` — манипулятор становился монохромным.
    Пять одинаковых серых значений — признак именно этой ошибки, а не выбор пользователя.
    Возвращает ``True``, если записи удалены.
    """
    g = group()
    if not all(g.GetUnsigned(key, 0) == UNSET_BUTTON_COLOR for key in COLOR_KEYS):
        return False
    for key in COLOR_KEYS:
        g.RemUnsigned(key)
    App.Console.PrintLog("Axel: сброшены цвета ручек, записанные без умолчаний\n")
    return True


CONFIG_VERSION = 6
"""Ступени 1–2 (цвета, смещение значка меню) сняты вместе со значком меню; номера не
переиспользуются — у ранних установок в ``user.cfg`` уже записано 2."""
OLD_DEFAULTS_V3 = {"OriginPx": 9}  # умолчания до ступени 3 (шарик начала уменьшен до 6)
OLD_DEFAULTS_V4_FLOAT = {"ShaftWidthPx": 2.5}  # до ступени 4 (линии тоньше, 1,5)
OLD_DEFAULTS_V5 = {"SizePx": 100}  # до ступени 5 (манипулятор на 20 % меньше, 80)
OLD_DEFAULTS_V6_COLOR = {"ColorHover": 0xFFD91AFF}  # до ступени 6 (подсветка жёлтая → чёрная)


def migrate() -> None:
    """Одноразовые исправления сохранённых параметров; пройденная ступень — ``ConfigVersion``.

    Страница настроек сохраняет все значения формы явными числами, поэтому прежнее умолчание
    остаётся в ``user.cfg`` и новое само не применится. Каждая ступень снимает ровно старое
    умолчание; любое другое значение — выбор пользователя, не трогается.
    """
    g = group()
    repair_unset_colors()  # по признаку, безопасно повторять
    version = g.GetInt("ConfigVersion", 0)
    if version < 3:
        for key, old in OLD_DEFAULTS_V3.items():
            if g.GetInt(key, old) == old:
                g.RemInt(key)
    if version < 4:
        for key, old in OLD_DEFAULTS_V4_FLOAT.items():
            if abs(g.GetFloat(key, old) - old) < 1e-9:
                g.RemFloat(key)
    if version < 5:
        for key, old in OLD_DEFAULTS_V5.items():
            if g.GetInt(key, old) == old:
                g.RemInt(key)
    if version < 6:
        for key, old in OLD_DEFAULTS_V6_COLOR.items():
            if g.GetUnsigned(key, old) == old:
                g.RemUnsigned(key)
    if version < CONFIG_VERSION:
        g.SetInt("ConfigVersion", CONFIG_VERSION)


def load_style() -> HandleStyle:
    """Размеры и цвета ручек из параметров, умолчания — из ``HandleStyle``."""
    g = group()
    d = HandleStyle()
    colors = tuple(
        unsigned_to_rgb(g.GetUnsigned(f"Color{axis}", rgb_to_unsigned(default)))
        for axis, default in zip("XYZ", DEFAULT_AXIS_COLORS, strict=True)
    )
    return HandleStyle(
        size_px=g.GetInt("SizePx", int(d.size_px)),
        shaft_width_px=g.GetFloat("ShaftWidthPx", d.shaft_width_px),
        origin_px=g.GetInt("OriginPx", int(d.origin_px)),
        axis_colors=colors,  # type: ignore[arg-type]
        transparency=g.GetInt("TransparencyPercent", round(d.transparency * 100)) / 100.0,
        hover_color=unsigned_to_rgb(g.GetUnsigned("ColorHover", rgb_to_unsigned(d.hover_color))),
        disabled_color=unsigned_to_rgb(
            g.GetUnsigned("ColorDisabled", rgb_to_unsigned(d.disabled_color))
        ),
    )


def load_settings() -> Settings:
    """Настройки математики и поведения из параметров."""
    g = group()
    d = Settings()
    return Settings(
        drag_strength_percent=g.GetInt("DragStrength", int(constants.DRAG_STRENGTH_PERCENT)),
        move_step_mm=g.GetFloat("MoveStep", d.move_step_mm),
        angle_step_deg=g.GetFloat("AngleStep", d.angle_step_deg),
        scale_step=g.GetFloat("ScaleStep", d.scale_step),
        allow_mirror=g.GetBool("AllowMirror", d.allow_mirror),
        degenerate_angle_deg=g.GetFloat("DegenerateAngleDeg", d.degenerate_angle_deg),
        step_enabled=g.GetBool("StepEnabled", d.step_enabled),
        auto_reset=g.GetBool("AutoReset", d.auto_reset),
        deselect_new_objects=g.GetBool("DeselectNewObjects", d.deselect_new_objects),
        alignment=read_enum("AlignmentDefault", ALIGNMENT_ORDER, d.alignment),
        origin_mode=read_enum("OriginDefault", ORIGIN_ORDER, d.origin_mode),
        show_tooltips=g.GetBool("ShowTooltips", d.show_tooltips),
        tooltip_delay_ms=g.GetInt("TooltipDelayMs", d.tooltip_delay_ms),
        shown_kinds=load_shown_kinds(),
        ring_radius_px=constants.ARC_RADIUS_FRACTION * g.GetInt("SizePx", constants.SIZE_PX),
        mod_step=read_enum("ModStep", MOD_ORDER, d.mod_step),
        mod_shape=read_enum("ModShape", MOD_ORDER, d.mod_shape),
        slider_step_px=g.GetInt("SliderStepPx", d.slider_step_px),
        recompute_during_drag=read_enum(
            "RecomputeDuringDrag", RECOMPUTE_ORDER, d.recompute_during_drag
        ),
        recompute_throttle_ms=g.GetInt("RecomputeThrottleMs", d.recompute_throttle_ms),
        proxy_preview_threshold=g.GetInt("ProxyPreviewThreshold", d.proxy_preview_threshold),
    )


HANDLE_GROUP_KEYS: dict[str, frozenset[HandleKind]] = {
    "ShowMove": frozenset({HandleKind.MOVE_AXIS, HandleKind.MOVE_FREE}),
    "ShowMove2D": frozenset({HandleKind.MOVE_PLANE}),
    "ShowRotate": frozenset({HandleKind.ROTATE}),
    "ShowScale": frozenset({HandleKind.SCALE_AXIS}),
    "ShowExtrude": frozenset({HandleKind.EXTRUDE}),
}


def load_shown_kinds() -> frozenset[HandleKind]:
    """Группы ручек, включённые в настройках (15.4 «Ручки»); по умолчанию все."""
    g = group()
    shown: set[HandleKind] = set()
    for key, kinds in HANDLE_GROUP_KEYS.items():
        if g.GetBool(key, True):
            shown |= kinds
    return frozenset(shown)


# ---------------------------------------------------------------------------
# Страница настроек (15.4) и слежение за параметрами
# ---------------------------------------------------------------------------

PAGE_GROUP = "Axel"
_page_added = False
_observer: _ParameterObserver | None = None
_watched_group: App.ParameterGrp | None = None
"""Обёртку группы нужно держать: с её удалением FreeCAD снимает и наблюдателя."""


def ui_path() -> Path:
    """Путь к форме страницы настроек."""
    return Path(__file__).resolve().parent.parent / "resources" / "ui" / "Preferences.ui"


def install_page() -> bool:
    """Добавить страницу настроек в диалог FreeCAD; повторный вызов безопасен."""
    global _page_added
    if _page_added:
        return True
    path = ui_path()
    if not path.exists():
        App.Console.PrintWarning(f"Axel: форма настроек не найдена: {path}\n")
        return False
    import FreeCADGui as Gui

    Gui.addPreferencePage(str(path), PAGE_GROUP)
    _page_added = True
    return True


def show_page() -> None:
    """Открыть диалог настроек FreeCAD на странице Axel."""
    import FreeCADGui as Gui

    install_page()
    Gui.showPreferences(PAGE_GROUP, 0)


class _ParameterObserver:
    """Перечитывает настройки Axel при изменении параметров группы (15.4)."""

    def __init__(self, on_change: object) -> None:
        self.on_change = on_change

    def slotParamChanged(self, param: object, kind: str, name: str, value: object) -> None:
        """Любое изменение в группе Axel — перечитать стиль и настройки."""
        self.on_change()


def watch(on_change: object) -> None:
    """Следить за группой параметров Axel; повторный вызов заменяет обработчик."""
    global _observer, _watched_group
    if _observer is not None:
        _observer.on_change = on_change
        return
    _observer = _ParameterObserver(on_change)
    _watched_group = group()  # обёртку держим: с её удалением подписка снимается
    try:
        _watched_group.AttachManager(_observer)
    except Exception as exc:  # noqa: BLE001 — без слежения настройки применятся при включении
        App.Console.PrintLog(f"Axel: слежение за параметрами недоступно: {exc!r}\n")
        _observer = None
        _watched_group = None


def unwatch() -> None:
    """Перестать следить за параметрами."""
    global _observer, _watched_group
    if _observer is None:
        return
    try:
        if _watched_group is not None:
            _watched_group.Detach(_observer)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintLog(f"Axel: отписка от параметров: {exc!r}\n")
    _observer = None
    _watched_group = None
