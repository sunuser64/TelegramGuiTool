import unittest
from unittest.mock import MagicMock, patch
from app.ui_controller import TelegramController, UIStateError
from app.clipboard_manager import ClipboardManager, ClipboardError


class ControllerTests(unittest.TestCase):
    def test_clipboard_verification_and_failure(self):
        with patch('pyperclip.copy') as copy, patch('pyperclip.paste', return_value='test'):
            ClipboardManager().copy('test')
            copy.assert_called_once_with('test')
            self.assertEqual(ClipboardManager().read(), 'test')
        with patch('pyperclip.copy', side_effect=OSError('busy')):
            with self.assertRaises(ClipboardError):
                ClipboardManager().copy('test')
        with patch('pyperclip.copy'), patch('pyperclip.paste', return_value='different'):
            with self.assertRaises(ClipboardError):
                ClipboardManager().copy('test', timeout=0.01)

    def test_uia_errors_are_safe_and_com_is_released(self):
        with patch('app.ui_controller.ctypes.windll.ole32.CoInitializeEx', return_value=0), \
             patch('app.ui_controller.ctypes.windll.ole32.CoUninitialize') as release, \
             patch.object(TelegramController, '_inspect', side_effect=TimeoutError()):
            with self.assertRaises(UIStateError):
                TelegramController().inspect()
            release.assert_called_once()

    def test_window_checks_and_only_control_counts_are_returned(self):
        window = MagicMock()
        window.handle = 17
        window.class_name.return_value = 'Qt51517QWindowIcon'
        window.is_visible.return_value = True
        window.is_enabled.return_value = True
        window.element_info.control_type = 'Window'
        window.iface_window.CurrentIsModal = False
        element = MagicMock()
        element.is_visible.return_value = True
        element.window_text.return_value = 'fictional label'
        element.element_info.control_type = 'Button'
        window.descendants.return_value = [element]
        with patch('pywinauto.Desktop') as desktop, \
             patch('psutil.Process') as process, \
             patch('app.ui_controller.ctypes.windll.user32.GetForegroundWindow', return_value=17) as foreground:
            process.return_value.exe.return_value = r'C:\Telegram\Telegram.exe'
            desktop.return_value.windows.return_value = [window]
            for class_name in ('Qt51517QWindowIcon', 'TelegramDesktopWindow', 'OtherWindowClass'):
                with self.subTest(class_name=class_name):
                    window.class_name.return_value = class_name
                    result = TelegramController()._inspect()
                    self.assertEqual(result, {'window_active': True, 'controls': {'Button': 1}, 'read_only': True})
            desktop.return_value.window.return_value.wait.assert_called_with('exists visible enabled', timeout=3)
            process.return_value.exe.return_value = r'C:\Other\Other.exe'
            with self.assertRaises(UIStateError):
                TelegramController()._inspect()
            process.return_value.exe.return_value = r'C:\Telegram\Telegram.exe'
            foreground.return_value = 99
            with self.assertRaises(UIStateError):
                TelegramController()._inspect()
            foreground.return_value = 17
            # Ordinary chat text and labels must never be treated as alerts.
            for text in ('Предупреждение платформы', 'Ошибка в примере', 'warning error', 'flood_wait'):
                element.window_text.return_value = text
                TelegramController()._inspect()
            element.window_text.assert_not_called()
            element.element_info.control_type = 'Window'
            element.class_name.return_value = 'QtDialog'
            element.iface_window.CurrentIsModal = True
            with self.assertRaisesRegex(UIStateError, 'UIA IsModal'):
                TelegramController()._inspect()
            element.iface_window.CurrentIsModal = False
            element.class_name.return_value = '#32770'
            with self.assertRaisesRegex(UIStateError, 'Win32 Dialog'):
                TelegramController()._inspect()
            element.element_info.control_type = 'Button'
            element.window_text.return_value = 'fictional label'
            foreground.side_effect = [17, 17, 99]
            with self.assertRaises(UIStateError):
                TelegramController()._inspect()
            desktop.return_value.windows.return_value = []
            with self.assertRaises(UIStateError):
                TelegramController()._inspect()

    def test_modal_foreground_and_missing_window_pattern(self):
        from pywinauto.uia_defines import NoPatternInterfaceError
        from unittest.mock import PropertyMock
        window = MagicMock()
        window.is_visible.return_value = True
        window.element_info.control_type = 'Window'
        window.class_name.return_value = 'TelegramDesktopWindow'
        window.iface_window.CurrentIsModal = True
        with self.assertRaisesRegex(UIStateError, 'UIA IsModal'):
            TelegramController._check_dialog(window)
        window.is_visible.return_value = False
        TelegramController._check_dialog(window)
        window.is_visible.return_value = True
        with patch.object(type(window), 'iface_window', new_callable=PropertyMock,
                          side_effect=NoPatternInterfaceError, create=True):
            TelegramController._check_dialog(window)
        window.window_text.assert_not_called()


if __name__ == '__main__':
    unittest.main()
