import threading
import unittest
from unittest.mock import MagicMock, patch
from app.chat_controller import TelegramChat
from app.timing import varied_delay
from app.ui_controller import UIStateError


class InputTimingTests(unittest.TestCase):
    def test_zero_variation_keeps_exact_delays(self):
        with patch('app.timing.random.uniform') as draw:
            self.assertEqual(varied_delay(2, 0), 2)
            draw.assert_not_called()

    def test_variation_uses_correct_range_and_independent_draws(self):
        with patch('app.timing.random.uniform', side_effect=[1.88, 2.12]) as draw:
            self.assertEqual(varied_delay(2, 0.2), 1.88)
            self.assertEqual(varied_delay(2, 0.2), 2.12)
            self.assertEqual(draw.call_count, 2)
            draw.assert_called_with(1.8, 2.2)

    def test_variation_cannot_make_negative_waits_and_validates_parameters(self):
        with patch('app.timing.random.uniform', return_value=0) as draw:
            self.assertEqual(varied_delay(0.1, 0.2), 0)
            low, high = draw.call_args.args
            self.assertEqual(low, 0)
            self.assertAlmostEqual(high, 0.3)
        for base, spread in ((-1, 0), (2, -1), (2, 61), (float('nan'), 0)):
            with self.subTest(base=base, spread=spread), self.assertRaises(ValueError):
                varied_delay(base, spread)

    def test_uia_moves_text_caret_to_end_after_setting_value(self):
        chat = TelegramChat('test_bot', threading.Event())
        chat.guard = MagicMock()
        element = MagicMock()
        element.iface_value.CurrentValue = 'test text'
        chat.set_value(element, 'test text')
        element.iface_value.SetValue.assert_called_once_with('test text')
        element.set_focus.assert_called_once()
        text_range = element.iface_text.DocumentRange
        text_range.MoveEndpointByRange.assert_called_once_with(0, text_range, 1)
        text_range.Select.assert_called_once()
        element.type_keys.assert_not_called()

    def test_caret_fallback_uses_only_focused_editor_and_never_presses_send(self):
        from pywinauto.uia_defines import NoPatternInterfaceError
        chat = TelegramChat('test_bot', threading.Event())
        chat.guard = MagicMock()
        element = MagicMock()
        element.iface_text.DocumentRange.MoveEndpointByRange.side_effect = NoPatternInterfaceError()
        element.has_keyboard_focus.return_value = True
        chat.move_caret_to_end(element)
        element.type_keys.assert_called_once_with('^{END}', set_foreground=False)
        element.type_keys.reset_mock()
        element.has_keyboard_focus.return_value = False
        with self.assertRaises(UIStateError):
            chat.move_caret_to_end(element)
        element.type_keys.assert_not_called()


if __name__ == '__main__':
    unittest.main()
