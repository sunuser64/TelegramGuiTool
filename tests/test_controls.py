import gc
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from app.database import Database
from app.main_window import MainWindow
from app.chat_controller import TelegramChat, ExchangeError
from app.ui_controller import UIStateError
from app.worker import TestWorker


class ControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.application.processEvents()
        gc.collect()
        self.temporary = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temporary.name) / 'progress.db')

    def tearDown(self):
        self.application.processEvents()
        gc.collect()
        self.temporary.cleanup()

    def wait_for(self, condition):
        end = time.monotonic() + 5
        while not condition() and time.monotonic() < end:
            QTest.qWait(20)
        self.assertTrue(condition())

    def test_preview_clears_on_restart_while_queue_and_options_are_preserved(self):
        run_id = self.db.create_run(['test_001', 'test_002'])
        self.db.bind_options(run_id, 'chat', 'test_bot')
        window = MainWindow(self.db)
        window.preview.setPlainText('previous displayed data')
        window.close()
        restarted = MainWindow(self.db)
        try:
            self.assertEqual(restarted.preview.toPlainText(), '')
            self.assertEqual(restarted.path.text(), '')
            self.assertEqual(restarted.run_id, run_id)
            self.assertEqual(restarted.total_value.text(), '2')
            self.assertTrue(restarted.resume.isEnabled())
            self.assertEqual(restarted.username.text(), 'test_bot')
        finally:
            restarted.close()

    def test_stop_cancels_start_and_resume_can_start_saved_queue(self):
        run_id = self.db.create_run(['hello'])
        window = MainWindow(self.db)
        try:
            window.mode.setCurrentIndex(2)
            window.username.setText('test_bot')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.start.click()
            self.assertTrue(window.timer.isActive())
            window.stop.click()
            self.assertFalse(window.timer.isActive())
            window.dispatch_pending()
            self.assertIsNone(window.worker)
            self.assertEqual(self.db.summary(run_id)['status'], 'stopped')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.resume.click()
            self.assertTrue(window.timer.isActive())
            window.stop.click()
            self.assertEqual(self.db.summary(run_id)['pending'], 1)
        finally:
            window.close()

    def test_pause_resume_stop_buttons_control_a_live_background_exchange(self):
        run_id = self.db.create_run(['hello', 'next'])
        started = threading.Event()
        window = MainWindow(self.db)

        class ControlledChat:
            def __init__(self, username, stop_event, reply_delay, checkpoint, delay_jitter=0):
                self.stop_event, self.checkpoint = stop_event, checkpoint
            def session(self):
                return nullcontext(self)
            def prepare_open_chat(self):
                self.checkpoint()
            def exchange(self, text, save):
                result = {'messages': [], 'send_attempted': True}
                save(result)
                started.set()
                try:
                    while True:
                        self.checkpoint()
                        self.stop_event.wait(0.01)
                except UIStateError as exc:
                    raise ExchangeError(str(exc), result) from None

        try:
            window.mode.setCurrentIndex(2)
            window.username.setText('test_bot')
            with patch('app.worker.TelegramChat', ControlledChat), \
                 patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.start.click()
                window.timer.stop()
                window.dispatch_pending()
                self.wait_for(started.is_set)
                window.pause.click()
                self.wait_for(lambda: window.worker.pause_acknowledged)
                self.application.processEvents()
                self.assertEqual(self.db.summary(run_id)['status'], 'paused')
                self.assertTrue(window.resume.isEnabled())
                window.resume.click()
                self.assertTrue(window.timer.isActive())
                self.assertTrue(window.worker.paused)
                # Simulate the expiry of the 5-second focus-return countdown.
                window.timer.stop()
                window.dispatch_pending()
                self.wait_for(lambda: self.db.summary(run_id)['status'] == 'running')
                window.stop.click()
                self.wait_for(lambda: window.worker is None)
            snapshot = self.db.snapshot(run_id)
            self.assertEqual(snapshot['status'], 'stopped')
            self.assertEqual([r['status'] for r in snapshot['records']], ['failed', 'pending'])
            self.assertTrue(snapshot['records'][0]['result']['send_attempted'])
            self.assertTrue(window.resume.isEnabled())
        finally:
            if window.worker:
                window.worker.stop()
                window.worker.wait(5000)
                self.application.processEvents()
            window.close()

    def test_stop_cancels_resume_countdown_and_unblocks_paused_worker(self):
        self.db.create_run(['hello'])
        window = MainWindow(self.db)
        worker = MagicMock()
        worker.paused = True
        worker.pause_acknowledged = True
        worker.isRunning.return_value = True
        worker.stop_event.is_set.return_value = False
        try:
            window.mode.setCurrentIndex(2)
            window.worker = worker
            window.refresh()
            window.resume.click()
            self.assertEqual(window.pending_action, 'resume')
            window.stop.click()
            self.assertFalse(window.timer.isActive())
            window.dispatch_pending()
            worker.stop.assert_called_once()
            worker.resume.assert_not_called()
        finally:
            window.worker = None
            window.close()

    def test_focus_grace_allows_pause_checkpoint_before_focus_error(self):
        chat = TelegramChat('test_bot', threading.Event())
        chat.window = MagicMock()
        chat.window.handle = 17
        chat.window.is_enabled.return_value = True
        chat.window.is_visible.return_value = True
        chat._check_dialog = MagicMock()
        chat.checkpoint = MagicMock()
        with patch('app.chat_controller.ctypes.windll.user32.GetForegroundWindow', side_effect=[99, 17]):
            chat.guard()
        self.assertEqual(chat.checkpoint.call_count, 2)

    def test_long_between_row_delay_responds_to_pause_and_stop(self):
        run_id = self.db.create_run(['hello', 'next'])
        worker = TestWorker(self.db, run_id, username='test_bot', inter_message_delay=30)
        with patch('app.worker.TelegramChat') as controller:
            controller.return_value.exchange.return_value = {'messages': ['reply'], 'send_attempted': True}
            worker.start()
            try:
                self.wait_for(lambda: self.db.summary(run_id)['completed'] == 1)
                worker.pause()
                self.wait_for(lambda: self.db.summary(run_id)['status'] == 'paused')
                worker.stop()
                self.assertTrue(worker.wait(5000))
            finally:
                worker.stop()
                worker.wait(5000)
        self.assertEqual(self.db.summary(run_id)['status'], 'stopped')
        self.assertEqual(self.db.summary(run_id)['pending'], 1)


if __name__ == '__main__':
    unittest.main()
