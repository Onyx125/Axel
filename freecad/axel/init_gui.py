"""Точка входа Axel при запуске FreeCAD с интерфейсом (раздел 13.1 спецификации).

Порядок запуска:
1. Подключение переводов (``resources/translations``) — до создания команд, чтобы их
   ресурсы сразу читались на языке интерфейса (15.5).
2. Регистрация команд, манипулятора меню и страницы настроек (``gui.commands``).
3. Встраивание команд во все верстаки — манипулятор применяется при активации верстака.
4. Кнопка в строке состояния (``gui.statusbar``).
5. Регистрация стандартных адаптеров и включение по настройке (``runtime.start``).
6. Проверка сочетаний двойных букв (``gui.commands.check_shortcut_conflicts``).

Ошибка на любом шаге пишется в отчёт и не мешает запуску FreeCAD (принцип 5.1.6).
"""

from pathlib import Path

import FreeCAD as App


def _install_translations() -> None:
    """Добавить каталог с ``.qm`` в пути переводов FreeCAD (15.5)."""
    import FreeCADGui as Gui

    path = Path(__file__).resolve().parent / "resources" / "translations"
    if not path.is_dir():
        return
    Gui.addLanguagePath(str(path))
    Gui.updateLocale()


def _startup() -> None:
    from freecad.axel.gui import commands, statusbar
    from freecad.axel.runtime import get_runtime

    _install_translations()
    commands.register_commands()
    statusbar.install()
    get_runtime().start()
    App.Console.PrintLog("Axel: started\n")


try:
    _startup()
except Exception as exc:  # noqa: BLE001 — принцип 5.1.6: не прерывать запуск FreeCAD
    App.Console.PrintError(f"Axel: startup failed: {exc!r}\n")
