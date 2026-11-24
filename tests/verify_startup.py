"""Manual startup smoke check: real main(), temporary DB and window render.

Run from project root: python tests/verify_startup.py
No Telegram interaction. Window closes automatically.
"""
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
import main as entry
from app.main_window import MainWindow
from app.settings import ROOT


application = QApplication([])
if not QFontDatabase.families():
    # Windows offscreen Qt does not enumerate installed fonts automatically.
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'))
errors = []


def load_example():
    try:
        window = next(w for w in application.topLevelWidgets() if isinstance(w, MainWindow))
        window.load_file(str(ROOT / 'data' / 'sample.txt'))
    except Exception as exc:
        errors.append(str(exc))
        application.quit()


def capture_and_close():
    try:
        window = next(w for w in application.topLevelWidgets() if isinstance(w, MainWindow))
        assert window.loader is None, 'TXT still loading'
        assert window.database.summary(window.run_id)['total'] == 3
        assert window.start.isEnabled()
        window.mode.setCurrentIndex(2)
        window.username.setText('@my_test_bot')
        assert window.grab().save(str(ROOT / 'exports' / 'gui_preview.png'))
        window.close()
    except Exception as exc:
        errors.append(str(exc))
    finally:
        application.quit()


with tempfile.TemporaryDirectory() as temporary:
    database_path = Path(temporary) / 'progress.db'
    QTimer.singleShot(200, load_example)
    QTimer.singleShot(1500, capture_and_close)
    with patch.object(entry, 'QApplication', return_value=application), patch.object(entry, 'DB_PATH', database_path):
        status = entry.main()
    if errors or status:
        raise SystemExit(f'Startup failed: {errors}, status={status}')
    print('Startup OK; TXT=3; GUI screenshot: exports/gui_preview.png')
