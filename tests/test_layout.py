import gc
import os
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QLabel, QBoxLayout
from PySide6.QtTest import QTest
from app.database import Database
from app.main_window import MainWindow


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        if not QFontDatabase.families():
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'))
        cls.application.setFont(QFont('Segoe UI', 10))

    def setUp(self):
        self.application.processEvents()
        gc.collect()
        self.temporary = tempfile.TemporaryDirectory()
        self.window = MainWindow(Database(Path(self.temporary.name) / 'progress.db'))
        self.window.mode.setCurrentIndex(2)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def assert_content_fits(self):
        root = self.window.workspace
        self.assertLessEqual(root.width(), self.window.workspace_scroll.viewport().width())
        for item in root.findChildren(QLabel):
            if item.text() and not item.isHidden():
                self.assertGreater(item.width(), 0, item.text())
                self.assertGreaterEqual(item.height(), item.heightForWidth(item.width()), item.text())
                position = item.mapTo(item.parentWidget(), item.rect().topLeft())
                self.assertGreaterEqual(position.x(), 0, item.text())
                self.assertLessEqual(position.x() + item.width(), item.parentWidget().width(), item.text())

    def test_reflow_and_text_bounds_at_small_short_and_large_window_sizes(self):
        self.window.status_badge.setText('Переключитесь в Telegram для продолжения · 5 секунд')
        self.window.file_info.setText('Записей: 150000 · UTF-8 · выбран файл с длинным названием и дополнительной информацией')
        for width, height in ((480, 420), (640, 480), (800, 600), (1080, 900), (1440, 1000), (1280, 520), (480, 420)):
            with self.subTest(width=width, height=height):
                self.window.resize(width, height)
                QTest.qWait(50)
                self.assertEqual(self.window.width(), width)
                self.assertEqual(self.window.height(), height)
                self.assert_content_fits()
                expected = QBoxLayout.Direction.TopToBottom if width < 900 else QBoxLayout.Direction.LeftToRight
                self.assertEqual(self.window.workspace.columns.direction(), expected)

    def test_long_unbroken_filename_does_not_force_horizontal_overflow(self):
        self.window.resize(480, 420)
        self.window.file_info.setText('filename_' + 'x' * 160 + '.txt')
        QTest.qWait(50)
        self.assert_content_fits()

    def test_small_window_can_scroll_to_every_control(self):
        self.window.resize(480, 420)
        QTest.qWait(50)
        scroll = self.window.workspace_scroll
        self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        for item in (self.window.mode, self.window.start, self.window.stop, self.window.export, self.window.logs):
            if item is self.window.logs:
                scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            else:
                scroll.ensureWidgetVisible(item)
            QTest.qWait(10)
            point = item.mapTo(scroll.viewport(), item.rect().center())
            self.assertTrue(scroll.viewport().rect().contains(point),
                            (item.objectName(), point, item.geometry(), scroll.verticalScrollBar().value(),
                             scroll.verticalScrollBar().maximum(), scroll.viewport().rect()))

    def test_select_popup_fits_control_width_and_remains_keyboard_operable(self):
        self.window.resize(480, 620)
        QTest.qWait(50)
        self.window.workspace_scroll.ensureWidgetVisible(self.window.mode)
        self.window.mode.setCurrentIndex(0)
        self.window.mode.setFocus()
        QTest.keyClick(self.window.mode, Qt.Key.Key_Down)
        self.assertEqual(self.window.mode.currentIndex(), 1)
        self.window.mode.showPopup()
        QTest.qWait(30)
        try:
            self.assertEqual(self.window.mode.view().window().width(), self.window.mode.width())
            self.assertEqual(self.window.mode.view().textElideMode(), Qt.TextElideMode.ElideRight)
        finally:
            self.window.mode.hidePopup()


if __name__ == '__main__':
    unittest.main()
