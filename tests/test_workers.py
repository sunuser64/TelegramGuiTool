import tempfile
import time
import gc
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from app.database import Database
from app.worker import TestWorker
from app.ui_controller import UIStateError
from app.main_window import MainWindow


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        # Dispose mock/GUI cycles on the owning thread before starting QThreads.
        self.application.processEvents()
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'progress.db')

    def tearDown(self):
        self.temp.cleanup()

    def wait_for(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(condition(), 'Ожидание операции истекло')

    def test_pause_stop_and_resume_persisted_queue(self):
        run_id = self.db.create_run([str(i) for i in range(8)])
        worker = TestWorker(self.db, run_id)
        worker.pause()
        worker.start()
        try:
            self.wait_for(lambda: self.db.summary(run_id)['status'] == 'paused')
            self.assertEqual(self.db.summary(run_id)['completed'], 0)
            worker.resume()
            self.wait_for(lambda: self.db.summary(run_id)['completed'] >= 1)
            worker.stop()
            self.assertTrue(worker.wait(5000))
            self.assertEqual(self.db.summary(run_id)['status'], 'stopped')
            self.assertEqual(self.db.recover(), run_id)
            resumed = TestWorker(self.db, run_id)
            resumed.start()
            self.assertTrue(resumed.wait(5000))
            self.assertEqual(self.db.summary(run_id)['completed'], 8)
            self.assertEqual(self.db.summary(run_id)['status'], 'finished')
        finally:
            worker.stop()
            worker.wait(5000)

    def test_unexpected_telegram_state_stops_remaining_tasks(self):
        run_id = self.db.create_run(['one', 'two'])
        with patch('app.worker.TelegramController.inspect', side_effect=UIStateError('Фокус потерян')):
            worker = TestWorker(self.db, run_id, True)
            worker.start()
            self.assertTrue(worker.wait(5000))
        summary = self.db.summary(run_id)
        self.assertEqual((summary['failed'], summary['pending'], summary['status']), (1, 1, 'stopped'))

    def test_individual_failure_does_not_abort_queue(self):
        run_id = self.db.create_run(['one', 'two'])
        with patch('app.worker.parse_message', side_effect=[ValueError('test failure'), {'messages': ['ok']}]):
            worker = TestWorker(self.db, run_id)
            worker.start()
            self.assertTrue(worker.wait(5000))
        summary = self.db.summary(run_id)
        self.assertEqual((summary['failed'], summary['completed'], summary['status']), (1, 1, 'finished'))

    def test_gui_load_run_export_and_restart(self):
        path = Path(self.temp.name) / 'sample.txt'
        path.write_text('test_001\n\nтест_002\n', encoding='utf-8-sig')
        window = MainWindow(self.db)
        window.mode.setCurrentIndex(0)
        window.show()
        try:
            window.load_file(str(path))
            self.wait_for(lambda: window.loader is None)
            self.assertEqual(self.db.summary(window.run_id)['total'], 2)
            self.assertTrue(window.start.isEnabled())
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.begin()
            self.wait_for(lambda: window.worker is None)
            self.assertEqual(window.progress.value(), 100)
            report = Path(self.temp.name) / 'export.json'
            with patch('app.main_window.QFileDialog.getSaveFileName', return_value=(str(report), 'JSON')):
                window.export_results()
            self.wait_for(lambda: window.exporter is None)
            self.assertTrue(report.exists())
        finally:
            window.close()
        restored = MainWindow(self.db)
        self.assertIsNone(restored.run_id)
        restored.close()

    def test_start_requires_user_confirmation(self):
        self.db.create_run(['test'])
        window = MainWindow(self.db)
        window.mode.setCurrentIndex(0)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            window.begin()
        self.assertIsNone(window.worker)
        self.assertEqual(self.db.summary(window.run_id)['pending'], 1)
        window.close()

    def test_chat_mode_confirms_recipient_and_restores_it_after_restart(self):
        self.db.create_run(['hello'])
        window = MainWindow(self.db)
        window.mode.setCurrentIndex(2)
        window.username.setText(' @My_Test_Bot ')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as confirmation:
            window.begin()
            self.assertIn('@my_test_bot', confirmation.call_args.args[2])
        self.assertTrue(window.timer.isActive())
        self.assertIsNone(window.worker)  # countdown never sends before it expires
        self.assertEqual(self.db.options(window.run_id)['username'], 'my_test_bot')
        window.stop_run()
        window.close()
        restored = MainWindow(self.db)
        self.assertEqual(restored.mode.currentIndex(), 2)
        self.assertEqual(restored.username.text(), 'my_test_bot')
        restored.close()

    def test_chat_mode_invalid_username_never_starts_countdown(self):
        self.db.create_run(['hello'])
        window = MainWindow(self.db)
        window.mode.setCurrentIndex(2)
        window.username.setText('https://t.me/example')
        with patch.object(QMessageBox, 'warning') as warning, patch.object(QMessageBox, 'question') as confirmation:
            window.begin()
            warning.assert_called_once()
            confirmation.assert_not_called()
        self.assertFalse(window.timer.isActive())
        self.assertIsNone(self.db.options(window.run_id))
        window.close()


if __name__ == '__main__':
    unittest.main()
