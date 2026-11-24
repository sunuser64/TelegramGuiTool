"""Render real Qt layouts at several sizes, without interacting with Telegram."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtTest import QTest
from app.main_window import MainWindow
from app.database import Database
from app.settings import ROOT

app = QApplication([])
app.setStyle('Fusion')
if not QFontDatabase.families():
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'))
app.setFont(QFont('Segoe UI', 10))
output = ROOT / 'exports' / 'layout'
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temporary:
    window = MainWindow(Database(Path(temporary) / 'progress.db'))
    window.mode.setCurrentIndex(2)
    window.status_badge.setText('Переключитесь в Telegram · 5 с')
    window.file_info.setText('Записей: 150000 · UTF-8 · файл с длинным названием и дополнительной информацией')
    window.show()
    for width, height in ((1080, 900), (480, 420), (640, 480), (800, 600), (1440, 1000), (1280, 520)):
        window.resize(width, height)
        QTest.qWait(100)
        scroll = window.workspace_scroll
        root = window.workspace
        assert root.width() <= scroll.viewport().width(), (width, height, root.width(), scroll.viewport().width())
        for item in root.findChildren(QLabel):
            if item.text() and not item.isHidden():
                needed = item.heightForWidth(item.width())
                assert item.width() > 0 and item.height() >= needed, (width, height, item.text(), item.size(), needed)
        scroll.verticalScrollBar().setValue(0)
        window.grab().save(str(output / f'{width}x{height}-top.png'))
        scroll.ensureWidgetVisible(window.export)
        QTest.qWait(30)
        window.grab().save(str(output / f'{width}x{height}-controls.png'))
        print(f'{width}x{height}: content={root.width()}x{root.height()}, scroll={scroll.verticalScrollBar().maximum()}', flush=True)
    window.resize(480, 620)
    QTest.qWait(100)
    window.workspace_scroll.ensureWidgetVisible(window.mode)
    QTest.qWait(30)
    window.mode.showPopup()
    QTest.qWait(50)
    window.mode.view().window().grab().save(str(output / 'select-popup.png'))
    window.mode.hidePopup()
    window.close()
print('Layout checks OK')
