import ctypes
import time


class UIStateError(RuntimeError):
    pass


class TelegramController:
    """Read-only inspection of an already focused official Telegram.exe window.

    No chat selection, text entry, clicks or sends. Never brings a window to front.
    """
    def __init__(self, timeout=3, checkpoint=None):
        self.timeout = timeout
        self.checkpoint = checkpoint

    def _foreground_handle(self):
        if self.checkpoint:
            self.checkpoint()
        return ctypes.windll.user32.GetForegroundWindow()

    @staticmethod
    def _check_dialog(element):
        """Use window metadata; message text cannot identify a platform alert."""
        from pywinauto.uia_defines import NoPatternInterfaceError
        if element.element_info.control_type != 'Window' or not element.is_visible():
            return
        if element.class_name() == '#32770':
            raise UIStateError('Обнаружен диалог Telegram (Win32 Dialog); проверка прервана.')
        try:
            modal = bool(element.iface_window.CurrentIsModal)
        except NoPatternInterfaceError:
            # Custom Qt controls may not expose WindowPattern. Do not infer
            # warnings from chat labels; this read-only check cannot classify them.
            return
        if modal:
            raise UIStateError('Обнаружено модальное окно Telegram (UIA IsModal); проверка прервана.')

    def inspect(self):
        initialized = False
        try:
            # UI Automation uses COM; each QThread must initialize its own apartment.
            status = ctypes.windll.ole32.CoInitializeEx(None, 0)
            if status not in (0, 1):
                raise UIStateError('Не удалось инициализировать COM для UI Automation.')
            initialized = True
            return self._inspect()
        except UIStateError:
            raise
        except Exception:
            raise UIStateError('Ошибка или таймаут Windows UI Automation; проверка остановлена.') from None
        finally:
            if initialized:
                ctypes.windll.ole32.CoUninitialize()

    def _active_window(self):
        from pathlib import Path
        from pywinauto import Desktop
        import psutil
        if self.checkpoint:
            self.checkpoint()
        windows = []
        for window in Desktop(backend='uia').windows():
            try:
                executable = psutil.Process(window.process_id()).exe()
                if Path(executable).name.lower() == 'telegram.exe':
                    windows.append(window)
            except (psutil.Error, OSError):
                continue
        if not windows:
            raise UIStateError('Окно Telegram Desktop не найдено. Запустите официальный клиент.')
        foreground = self._foreground_handle()
        window = next((item for item in windows if item.handle == foreground), None)
        if window is None:
            if self.checkpoint:
                time.sleep(0.2)
                foreground = self._foreground_handle()
                window = next((item for item in windows if item.handle == foreground), None)
        if window is None:
            raise UIStateError('Telegram неактивен. Активируйте его вручную и повторите тест.')
        return window

    def _inspect(self):
        from pywinauto import Desktop
        window = self._active_window()
        def validate_focus():
            if self._foreground_handle() != window.handle:
                if self.checkpoint:
                    time.sleep(0.2)
                    if self._foreground_handle() == window.handle:
                        return
                raise UIStateError('Фокус Telegram потерян; проверка прервана.')
        validate_focus()
        if not window.is_visible() or not window.is_enabled():
            raise UIStateError('Неожиданное состояние окна Telegram.')
        # Process identity and foreground HWND select the target. A window class
        # is an implementation detail, not a stable Telegram identity check.
        Desktop(backend='uia').window(handle=window.handle).wait('exists visible enabled', timeout=self.timeout)
        self._check_dialog(window)
        validate_focus()
        elements = window.descendants()
        counts = {}
        for element in elements:
            validate_focus()
            self._check_dialog(element)
            kind = element.element_info.control_type
            counts[kind] = counts.get(kind, 0) + 1
        validate_focus()
        return {'window_active': True, 'controls': counts, 'read_only': True}
