import gc
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from app.database import Database
from app.main_window import MainWindow
from app.worker import TestWorker
from app.chat_controller import ExchangeError


class ReconfigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.app.processEvents()
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'progress.db')

    def tearDown(self):
        self.app.processEvents()
        gc.collect()
        self.temp.cleanup()

    def wait_for(self, predicate):
        until = time.monotonic() + 5
        while not predicate() and time.monotonic() < until:
            QTest.qWait(20)
        self.assertTrue(predicate())

    def test_send_mode_is_default_even_when_a_local_queue_is_restored(self):
        run_id = self.db.create_run(['test'])
        self.db.bind_options(run_id, 'local')
        window = MainWindow(self.db)
        try:
            self.assertEqual(window.mode.currentIndex(), 2)
            self.assertTrue(window.username.isEnabled())
        finally:
            window.close()

    def test_step_buttons_use_point_one_and_leave_no_text_selection(self):
        window = MainWindow(self.db)
        window.show()
        try:
            for field in (window.reply_delay, window.inter_message_delay, window.delay_jitter):
                self.assertEqual(field.singleStep(), 0.1)
                window.workspace_scroll.ensureWidgetVisible(field)
                field.setValue(2)
                field.setFocus()
                field.selectAll()
                QTest.mouseClick(field.plus, Qt.MouseButton.LeftButton)
                self.app.processEvents()
                self.assertAlmostEqual(field.value(), 2.1)
                self.assertFalse(field.lineEdit().hasSelectedText())
                self.assertGreaterEqual(field.lineEdit().width(), field.fontMetrics().horizontalAdvance(field.text()))
                self.assertGreaterEqual(field.lineEdit().height(), field.fontMetrics().height())
                QTest.mouseClick(field.minus, Qt.MouseButton.LeftButton)
                self.assertAlmostEqual(field.value(), 2)
                self.assertFalse(field.lineEdit().hasSelectedText())
        finally:
            window.close()

    def test_mode_and_file_can_be_changed_after_start_without_restarting(self):
        self.db.create_run(['old'])
        file = Path(self.temp.name) / 'new.txt'
        file.write_text('new_001\nnew_002\n', encoding='utf-8')
        window = MainWindow(self.db)
        try:
            window.username.setText('test_bot')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.start.click()
            self.assertTrue(window.timer.isActive())
            self.assertTrue(window.mode.isEnabled())
            self.assertTrue(window.choose.isEnabled())
            window.mode.setCurrentIndex(0)
            self.assertFalse(window.timer.isActive())
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.start.click()
            self.wait_for(lambda: window.worker is None)
            self.assertEqual(self.db.summary(window.run_id)['completed'], 1)
            with patch('app.main_window.QFileDialog.getOpenFileName', return_value=(str(file), 'TXT')):
                window.choose.click()
            self.wait_for(lambda: window.loader is None)
            self.assertEqual(self.db.summary(window.run_id)['pending'], 2)
            self.assertEqual(window.preview.toPlainText(), 'new_001\nnew_002')
        finally:
            window.timer.stop()
            if window.worker:
                window.worker.stop()
                window.worker.wait(5000)
                self.app.processEvents()
            window.close()

    def test_new_file_waits_for_active_worker_to_finish_before_replacing_queue(self):
        old_id = self.db.create_run(['old'])
        file = Path(self.temp.name) / 'new.txt'
        file.write_text('new', encoding='utf-8')
        window = MainWindow(self.db)
        worker = MagicMock()
        worker.isRunning.return_value = True
        worker.paused = False
        worker.stop_event = threading.Event()
        worker.stop.side_effect = worker.stop_event.set
        window.worker = worker
        try:
            window.refresh()
            self.assertTrue(window.choose.isEnabled())
            self.assertTrue(window.mode.isEnabled())
            window.load_file(str(file))
            self.assertTrue(worker.stop_event.is_set())
            self.assertEqual(window.run_id, old_id)
            self.assertIsNone(window.loader)
            window.worker_finished()
            self.wait_for(lambda: window.loader is None)
            self.assertNotEqual(window.run_id, old_id)
            self.assertEqual(self.db.preview(window.run_id), ['new'])
            self.assertEqual(self.db.preview(old_id), ['old'])
        finally:
            window.worker = None
            window.close()

    def test_new_mode_copies_only_pending_rows_and_preserves_previous_results(self):
        old_id = self.db.create_run(['completed', 'pending'])
        task = self.db.claim(old_id)
        self.db.finish_task(task['id'], 'completed', {'messages': ['reply']})
        self.db.bind_options(old_id, 'chat', 'test_bot')
        window = MainWindow(self.db)
        try:
            window.mode.setCurrentIndex(0)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
                window.begin()
            self.assertNotEqual(window.run_id, old_id)
            self.assertEqual(self.db.preview(window.run_id), ['pending'])
            self.assertEqual(self.db.summary(old_id)['completed'], 1)
        finally:
            window.close()

    def test_reconfiguration_before_send_preserves_the_current_pending_row(self):
        run_id = self.db.create_run(['current', 'next'])
        worker = TestWorker(self.db, run_id)
        chat = MagicMock()
        def cancelled_before_send(text, save):
            worker.stop_event.set()
            raise ExchangeError('Остановка', {'messages': [], 'send_attempted': False})
        chat.exchange.side_effect = cancelled_before_send
        worker.process_queue(chat)
        self.assertEqual(self.db.summary(run_id)['pending'], 2)
        self.assertEqual(self.db.summary(run_id)['failed'], 0)
        copied = self.db.clone_pending(run_id)
        self.assertEqual(self.db.preview(copied), ['current', 'next'])


if __name__ == '__main__':
    unittest.main()
