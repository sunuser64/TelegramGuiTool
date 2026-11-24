import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.chat_controller import TelegramChat, Message, ExchangeError, normalize_username, new_outgoing_positions
from app.ui_controller import UIStateError
from app.database import Database
from app.worker import TestWorker


def msg(number, text, incoming=True):
    return Message((number,), text, incoming)


class Clock:
    def __init__(self):
        self.value = 0
    def now(self):
        return self.value
    def wait(self, delay):
        self.value += delay


class ChatTests(unittest.TestCase):
    def chat(self):
        return TelegramChat('Test_Bot', threading.Event())

    def test_profile_dividers_are_not_dialogs_but_overlay_box_content_is(self):
        chat = self.chat()
        chat.window = MagicMock()
        chat.window.handle = 17
        chat.window.is_visible.return_value = True
        chat.window.is_enabled.return_value = True
        chat._check_dialog = MagicMock()
        element = MagicMock()
        element.is_visible.return_value = True
        chat.window.descendants.return_value = [element]
        root = 'class Core::Sandbox.class MainWindow.class Ui::RpWidget.'
        accepted = [
            root + 'class MainWidget.class Info::SectionWidget.class Ui::BoxContentDivider',
            root + 'class Ui::LayerStackWidget.class Info::LayerWidget.class Ui::BoxContentDivider',
            root + 'class MainWidget.class Ui::BoxContent',
        ]
        with patch('app.chat_controller.ctypes.windll.user32.GetForegroundWindow', return_value=17):
            for identifier in accepted:
                with self.subTest(identifier=identifier):
                    element.element_info.automation_id = identifier
                    chat.guard(dialogs=True)
            element.element_info.automation_id = root + 'class Ui::LayerStackWidget.class Ui::BoxContent.class Ui::Label'
            with self.assertRaisesRegex(UIStateError, 'LayerStackWidget / BoxContent'):
                chat.guard(dialogs=True)
            element.is_visible.return_value = False
            chat.guard(dialogs=True)

    def test_username_validation(self):
        self.assertEqual(normalize_username(' @Test_Bot '), 'test_bot')
        for value in ('', 'https://t.me/test_bot', 'foo bar', '@@test_bot', 'тест_бот', 'user\nname'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_username(value)

    def test_reads_once_after_three_seconds_and_keeps_every_incoming(self):
        chat, clock = self.chat(), Clock()
        chat.stop_event = clock
        read_times = []
        def read():
            read_times.append(clock.value)
            return [msg(1, 'old'), msg(2, 'request', False)] + [msg(i + 3, 'same reply') for i in range(25)]
        chat.read_messages = read
        result = {'messages': []}
        chat.collect('request', [msg(1, 'old')], result, lambda _: None)
        self.assertEqual(read_times, [3])
        self.assertEqual(result['messages'], ['same reply'] * 25)
        self.assertEqual(result['completion_reason'], 'snapshot_after_delay')

    def test_stop_during_delay_prevents_reading(self):
        chat = self.chat()
        chat.stop_event.set()
        chat.read_messages = MagicMock()
        with self.assertRaises(UIStateError):
            chat.collect('request', [], {'messages': []}, lambda _: None)
        chat.read_messages.assert_not_called()


    def test_old_replies_and_outgoing_echo_are_not_answers(self):
        chat, clock = self.chat(), Clock()
        chat.stop_event = clock
        outgoing = msg(3, 'request', False)
        old = msg(1, 'old')
        unrelated_before_send = msg(2, 'not a reply')
        chat.read_messages = lambda: [old, unrelated_before_send, outgoing]
        result = {'messages': []}
        with patch('app.chat_controller.time.monotonic', clock.now):
            chat.collect('request', [old], result, lambda _: None)
        self.assertEqual(result['messages'], [])
        self.assertEqual(result['completion_reason'], 'snapshot_after_delay')
        self.assertEqual(clock.value, 3)

    def test_confirmation_ignores_reused_and_rebuilt_runtime_ids(self):
        before = [msg(1, 'old request', False), msg(2, 'old reply')]
        reused = [msg(1, 'request', False), msg(2, 'new reply')]
        self.assertEqual(new_outgoing_positions(before, reused, 'request'), [0])
        rebuilt = [msg(99, 'old request', False), msg(100, 'old reply')]
        self.assertEqual(new_outgoing_positions(before, rebuilt, 'old request'), [])

    def test_repeated_identical_request_is_identified_by_order_and_occurrence(self):
        before = [msg(1, 'request', False), msg(2, 'reply')]
        after = [msg(8, 'request', False), msg(9, 'reply'), msg(1, 'request', False), msg(2, 'reply')]
        self.assertEqual(new_outgoing_positions(before, after, 'request'), [2])
        # Telegram may trim surrounding whitespace on send.
        self.assertEqual(new_outgoing_positions([], [msg(1, 'request', False)], ' request '), [0])

    def test_history_prefix_eviction_preserves_new_outgoing_boundary(self):
        before = [msg(1, 'older'), msg(2, 'last old reply')]
        after = [msg(99, 'last old reply'), msg(1, 'request', False), msg(2, 'answer')]
        self.assertEqual(new_outgoing_positions(before, after, 'request'), [1])

    def test_confirmation_can_reread_a_late_outgoing_without_resending(self):
        chat, clock = self.chat(), Clock()
        chat.stop_event = clock
        before = [msg(1, 'old')]
        chat.read_messages = MagicMock(side_effect=[before, before + [msg(2, 'request', False), msg(3, 'answer')]])
        chat.click = MagicMock()
        result = {'messages': []}
        chat.collect('request', before, result, lambda _: None)
        self.assertEqual(result['messages'], ['answer'])
        self.assertEqual(result['confirmation']['read_attempt'], 2)
        self.assertEqual(clock.value, 3.2)
        chat.click.assert_not_called()

    def test_ambiguous_or_unobserved_send_still_stops_without_resending(self):
        for history in ([msg(1, 'request', False), msg(2, 'request', False)], [msg(3, 'unrelated')]):
            chat, clock = self.chat(), Clock()
            chat.stop_event = clock
            chat.read_messages = MagicMock(return_value=history)
            chat.click = MagicMock()
            result = {'messages': []}
            with self.assertRaises(UIStateError):
                chat.collect('request', [], result, lambda _: None)
            self.assertIn('new_matching_outgoing', result['confirmation'])
            chat.click.assert_not_called()

    def test_reused_reply_keys_do_not_drop_distinct_messages(self):
        chat, clock = self.chat(), Clock()
        chat.stop_event = clock
        chat.read_messages = MagicMock(return_value=[msg(1, 'request', False),
            msg(2, 'first'), msg(2, 'second'), msg(3, 'second')])
        result = {'messages': []}
        chat.collect('request', [], result, lambda _: None)
        self.assertEqual(result['messages'], ['first', 'second', 'second'])


    def test_message_adapter_uses_delivery_and_stable_runtime_identity(self):
        chat = self.chat()
        chat.guard = MagicMock()
        chat.verify_chat = MagicMock()
        history, item = MagicMock(), MagicMock()
        item.element_info.runtime_id = [1, 2, 3]
        fields = {'Message': 'reply', 'Delivery': 'Received', 'Sender': 'Test Bot', 'Time': '12:00'}
        children = []
        for name, value in fields.items():
            child = MagicMock()
            child.window_text.return_value = name
            child.iface_value.CurrentValue = value
            children.append(child)
        item.children.return_value = children
        history.children.return_value = [item]
        chat.unique = MagicMock(return_value=history)
        first = chat.read_messages()[0]
        self.assertTrue(first.incoming)
        children[0].iface_value.CurrentValue = 'edited reply'
        second = chat.read_messages()[0]
        self.assertEqual(first.key, second.key)
        self.assertEqual(second.text, 'edited reply')
        children[1].iface_value.CurrentValue = 'unknown'
        with self.assertRaises(UIStateError):
            chat.read_messages()

    def test_profile_layer_is_not_accepted_as_active_chat_identity(self):
        chat = self.chat()
        label = MagicMock()
        label.element_info.automation_id = 'Info::LayerWidget.class Info::Profile::InnerWidget'
        value = MagicMock()
        value.is_visible.return_value = True
        value.element_info.control_type = 'Text'
        value.window_text.return_value = '@test_bot'
        label.parent.return_value.parent.return_value.descendants.return_value = [value]
        chat.elements = MagicMock(return_value=[label])
        self.assertFalse(chat.verify_username())
        label.element_info.automation_id = 'MainWidget.class Info::SectionWidget.class Info::Profile::InnerWidget'
        self.assertTrue(chat.verify_username())
        value.window_text.return_value = '@other_bot'
        self.assertFalse(chat.verify_username())

    def test_prepares_current_chat_without_searching_or_selecting(self):
        chat = self.chat()
        chat.window = MagicMock()
        chat.window.window_text.return_value = 'Current conversation'
        chat.guard = MagicMock()
        chat.editor = MagicMock()
        chat.editor.return_value.iface_value.CurrentValue = ''
        chat.verify_username = MagicMock(return_value=True)
        chat.read_messages = MagicMock(return_value=[])
        chat.set_value = MagicMock()
        chat.click = MagicMock()
        chat.prepare_open_chat()
        chat.set_value.assert_not_called()
        chat.click.assert_not_called()
        chat.read_messages.assert_called_once()
        chat.window.window_text.assert_not_called()
        chat.verify_username.assert_called_once()
        self.assertTrue(chat.chat_confirmed)
        chat.verify_username.reset_mock()
        for _ in range(3):
            chat.verify_chat()
        chat.verify_username.assert_not_called()

    def test_opens_only_current_chat_info_and_refuses_unconfirmed_username(self):
        chat = self.chat()
        chat.window = MagicMock()
        chat.guard = MagicMock()
        chat.editor = MagicMock()
        chat.editor.return_value.iface_value.CurrentValue = ''
        chat.verify_username = MagicMock(return_value=False)
        info_button = MagicMock()
        chat.unique = MagicMock(return_value=info_button)
        chat.click = MagicMock()
        chat.set_value = MagicMock()
        chat.wait = MagicMock(side_effect=UIStateError('Timeout'))
        chat.read_messages = MagicMock()
        with self.assertRaisesRegex(UIStateError, 'Username открытой переписки'):
            chat.prepare_open_chat()
        chat.unique.assert_called_once_with(kind='Button', marker='HistoryView::TopBarWidget',
                                            names={'Info', 'Информация'})
        chat.click.assert_called_once_with(info_button)
        chat.set_value.assert_not_called()
        chat.read_messages.assert_not_called()


    def test_iterations_check_focus_without_rechecking_profile_or_caption(self):
        chat = self.chat()
        chat.guard = MagicMock()
        chat.verify_username = MagicMock(return_value=True)
        chat.window = MagicMock()
        with self.assertRaisesRegex(UIStateError, 'перед запуском'):
            chat.verify_chat()
        chat.chat_confirmed = True
        for title in ('Test Bot @ Account (124)', '\u200eTest Bot @ Account (1,234)',
                      'Connecting...', 'Test Bot — typing...', 'Telegram'):
            chat.window.window_text.return_value = title
            chat.verify_chat()
        chat.window.window_text.assert_not_called()
        chat.verify_username.assert_not_called()
        chat.guard.side_effect = UIStateError('Фокус потерян')
        with self.assertRaises(UIStateError):
            chat.verify_chat()




    def test_read_retries_transient_snapshot_failure_without_repeating_send(self):
        chat = self.chat()
        chat.guard = MagicMock()
        chat.stop_event = MagicMock()
        chat._read_messages_once = MagicMock(side_effect=[RuntimeError('private text'), [msg(1, 'reply')]])
        self.assertEqual(chat.read_messages(), [msg(1, 'reply')])
        self.assertEqual(chat._read_messages_once.call_count, 2)
        chat._read_messages_once = MagicMock(side_effect=RuntimeError('private text'))
        with self.assertRaises(UIStateError) as error:
            chat.read_messages()
        self.assertNotIn('private text', str(error.exception))
        self.assertIn('RuntimeError', str(error.exception))
        self.assertEqual(chat._read_messages_once.call_count, 3)
        chat._read_messages_once = MagicMock(side_effect=UIStateError('Фокус потерян'))
        with self.assertRaises(UIStateError):
            chat.read_messages()
        chat._read_messages_once.assert_called_once()

    def test_wrong_chat_or_draft_prevents_send(self):
        chat = self.chat()
        chat.verify_chat = MagicMock(side_effect=UIStateError('Username не подтверждён'))
        chat.click = MagicMock()
        with self.assertRaises(ExchangeError) as error:
            chat.exchange('hello', lambda _: self.fail('Must not persist a send intent'))
        self.assertFalse(error.exception.result['send_attempted'])
        chat.click.assert_not_called()
        chat.verify_chat.side_effect = None
        chat.editor = MagicMock()
        chat.editor.return_value.iface_value.CurrentValue = 'existing draft'
        with self.assertRaises(ExchangeError):
            chat.exchange('hello', lambda _: self.fail('Must not persist a send intent'))
        chat.click.assert_not_called()

    def test_send_intent_is_durable_before_click_and_failure_is_not_retried(self):
        chat = self.chat()
        chat.verify_chat = MagicMock()
        chat.guard = MagicMock()
        chat.editor = MagicMock()
        chat.editor.return_value.iface_value.CurrentValue = ''
        chat.read_messages = MagicMock(return_value=[])
        chat.set_value = MagicMock()
        chat.unique = MagicMock()
        order = []
        def click(_):
            order.append('click')
            raise RuntimeError('UIA details must not escape')
        chat.click = click
        def save(result):
            self.assertTrue(result['send_attempted'])
            order.append('save')
        with self.assertRaises(ExchangeError) as error:
            chat.exchange('hello', save)
        self.assertEqual(order, ['save', 'click'])
        self.assertTrue(error.exception.result['send_attempted'])
        self.assertNotIn('UIA details', str(error.exception))

    def test_keyboard_controls_and_empty_strings_are_not_sent(self):
        chat = self.chat()
        chat.verify_chat = MagicMock()
        for value in ('', '   ', 'hello\nworld', 'hello\tworld'):
            with self.subTest(value=value), self.assertRaises(ExchangeError):
                chat.exchange(value, lambda _: self.fail('Must not send'))
        chat.verify_chat.assert_not_called()

    def test_recovery_never_repeats_an_ambiguous_external_send(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['first', 'second'])
            db.bind_options(run_id, 'chat', 'test_bot')
            first = db.claim(run_id)
            db.save_processing_result(first['id'], {'send_attempted': True, 'messages': ['partial']})
            db.recover()
            records = db.snapshot(run_id)['records']
            self.assertEqual(records[0]['status'], 'failed')
            self.assertEqual(records[0]['result']['messages'], ['partial'])
            self.assertEqual(db.summary(run_id)['failed'], 1)
            self.assertEqual(db.claim(run_id)['input'], 'second')
            with self.assertRaises(ValueError):
                db.bind_options(run_id, 'chat', 'other_bot')
            self.assertEqual(db.options(run_id)['username'], 'test_bot')
            self.assertEqual(db.options(run_id)['mode'], 'chat')

    def test_worker_real_mode_saves_real_results_without_fixture_parser(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['first'])
            with patch('app.worker.TelegramChat') as controller, patch('app.worker.fixture_message') as fixture:
                controller.return_value.exchange.return_value = {'messages': ['real reply'], 'send_attempted': True}
                worker = TestWorker(db, run_id, username='test_bot')
                worker.run()
                fixture.assert_not_called()
                controller.return_value.prepare_open_chat.assert_called_once()
            self.assertEqual(db.snapshot(run_id)['records'][0]['result']['messages'], ['real reply'])

    def test_timeout_preserves_partial_reply_and_stops_the_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['first', 'second'])
            with patch('app.worker.TelegramChat') as controller:
                controller.return_value.exchange.side_effect = ExchangeError('Таймаут',
                    {'messages': ['partial'], 'send_attempted': True})
                TestWorker(db, run_id, username='test_bot').run()
                controller.return_value.exchange.assert_called_once()
            records = db.snapshot(run_id)['records']
            self.assertEqual([r['status'] for r in records], ['failed', 'pending'])
            self.assertEqual(records[0]['result']['messages'], ['partial'])


if __name__ == '__main__':
    unittest.main()
