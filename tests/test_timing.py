import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication, QMessageBox
from app.database import Database
from app.main_window import MainWindow
from app.worker import TestWorker
from app.exporter import export_run
from app.chat_controller import TelegramChat, Message


class TimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_existing_database_migrates_without_losing_run_or_recipient(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'progress.db'
            with closing(sqlite3.connect(path)) as old:
                old.execute('CREATE TABLE run_options(run_id INTEGER PRIMARY KEY,mode TEXT,username TEXT)')
                old.execute("INSERT INTO run_options VALUES(1,'chat','test_bot')")
                old.commit()
            db = Database(path)
            self.assertEqual(db.options(1)['username'], 'test_bot')
            self.assertEqual(db.options(1)['reply_delay'], 3)
            self.assertEqual(db.options(1)['inter_message_delay'], 2)

    def test_two_iterations_follow_send_wait_three_read_wait_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['first', 'second'])
            worker = TestWorker(db, run_id, username='test_bot')
            events = []
            event = MagicMock()
            event.is_set.return_value = False
            event.wait.side_effect = lambda delay: events.append(('wait', delay)) or False
            worker.stop_event = event
            worker.wait_between_iterations = event.wait
            chat = TelegramChat('test_bot', event)
            history = []
            def read():
                events.append(('read', None))
                return list(history)
            chat.read_messages = read
            def exchange(text, save):
                baseline = list(history)
                events.append(('send', text))
                history.append(Message((len(history),), text, False))
                history.append(Message((len(history),), 'reply ' + text, True))
                return chat.collect(text, baseline, {'messages': []}, save)
            chat.exchange = exchange
            worker.process_queue(chat)
            self.assertEqual(events, [
                ('send', 'first'), ('wait', 3), ('read', None), ('wait', 2),
                ('send', 'second'), ('wait', 3), ('read', None), ('wait', 2)])
            self.assertEqual([row['result']['messages'] for row in db.snapshot(run_id)['records']],
                             [['reply first'], ['reply second']])

    def test_timings_can_change_for_same_recipient_and_are_exported(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['hello'])
            db.bind_options(run_id, 'chat', 'test_bot')
            db.bind_options(run_id, 'chat', 'test_bot', 4, 2)
            self.assertEqual(db.options(run_id)['reply_delay'], 4)
            report = Path(temporary) / 'out.json'
            export_run(db, run_id, report)
            self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['options']['reply_delay'], 4)
            with self.assertRaises(ValueError):
                db.bind_options(run_id, 'chat', 'other_bot', 4, 2)
            with self.assertRaises(ValueError):
                db.bind_options(run_id, 'chat', 'test_bot', -1)

    def test_gui_persists_timing_and_passes_it_to_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['hello'])
            window = MainWindow(db)
            try:
                window.mode.setCurrentIndex(2)
                window.username.setText('@test_bot')
                window.reply_delay.setValue(4)
                window.inter_message_delay.setValue(2)
                window.delay_jitter.setValue(0.2)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as confirmation:
                    window.begin()
                    self.assertIn('4 с', confirmation.call_args.args[2])
                window.timer.stop()
                with patch('app.main_window.TestWorker') as worker:
                    window.launch_worker()
                    arguments = worker.call_args.kwargs
                    self.assertEqual(arguments['reply_delay'], 4)
                    self.assertEqual(arguments['inter_message_delay'], 2)
                    self.assertEqual(arguments['delay_jitter'], 0.2)
                    window.worker = None
            finally:
                window.timer.stop()
                window.close()
            restored = MainWindow(db)
            try:
                self.assertEqual(restored.reply_delay.value(), 4)
                self.assertEqual(restored.inter_message_delay.value(), 2)
                self.assertEqual(restored.delay_jitter.value(), 0.2)
            finally:
                restored.close()

    def test_snapshot_with_no_reply_is_saved_and_queue_continues(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / 'progress.db')
            run_id = db.create_run(['first', 'second'])
            with patch('app.worker.TelegramChat') as controller:
                controller.return_value.exchange.return_value = {
                    'messages': [], 'send_attempted': True, 'outgoing_observed': True,
                    'completion_reason': 'snapshot_after_delay', 'reply_complete': False}
                worker = TestWorker(db, run_id, username='test_bot', reply_delay=4, inter_message_delay=0)
                worker.run()
                self.assertEqual(controller.return_value.exchange.call_count, 2)
                self.assertEqual(controller.call_args.kwargs['reply_delay'], 4)
            snapshot = db.snapshot(run_id)
            self.assertEqual(snapshot['completed'], 2)
            self.assertEqual(snapshot['records'][0]['result']['messages'], [])


if __name__ == '__main__':
    unittest.main()
