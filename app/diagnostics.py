"""Explicit offline EXE smoke check. Never opens or sends messages to Telegram."""
import json
import sys
import tempfile
import platform
import traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from . import __version__
from .database import Database
from .file_manager import load_txt
from .exporter import export_run
from .worker import TestWorker
from .main_window import MainWindow
from .settings import SAMPLE_PATH, RESOURCE_ROOT


def self_test(argv):
    index = argv.index('--self-test')
    if index + 1 >= len(argv):
        return 2
    target = Path(argv[index + 1]).resolve()
    report = {'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
              'python': platform.python_version(), 'checks': {}, 'success': False}
    window = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exercise dynamic Windows dependencies, including the UIA COM wrapper.
        import pywinauto
        from pywinauto.uia_defines import IUIA
        import pyautogui
        import pyperclip
        import psutil
        IUIA()
        report['checks']['windows_dependencies'] = True
        application = QApplication.instance() or QApplication([argv[0]])
        application.setStyle('Fusion')
        if not QFontDatabase.families():
            import os
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'))
        application.setFont(QFont('Segoe UI', 10))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loaded = load_txt(SAMPLE_PATH)
            database = Database(root / 'progress.db')
            run_id = database.create_run(loaded.lines)
            TestWorker(database, run_id).run()
            snapshot = database.snapshot(run_id)
            if snapshot['completed'] != 3 or snapshot['failed']:
                raise RuntimeError('Local queue did not complete three sample rows.')
            report['checks']['txt_sqlite_local_worker'] = True
            export_run(database, run_id, root / 'results.json')
            exported = json.loads((root / 'results.json').read_text(encoding='utf-8'))
            if exported['completed'] != 3 or 'messages' not in exported['records'][0]['result']:
                raise RuntimeError('Export verification failed.')
            report['checks']['json_export'] = True
            if Database(root / 'progress.db').recover() is not None:
                raise RuntimeError('Finished run unexpectedly recovered.')
            report['checks']['recovery'] = True
            if not (RESOURCE_ROOT / 'app' / 'assets' / 'chevron-down.svg').exists():
                raise RuntimeError('Bundled interface asset is missing.')
            report['checks']['bundled_assets'] = True
            window = MainWindow(database)
            window.show()
            application.processEvents()
            for width, height in ((480, 420), (1080, 900)):
                window.resize(width, height)
                application.processEvents()
                if window.workspace.width() > window.workspace_scroll.viewport().width():
                    raise RuntimeError('Horizontal UI overflow.')
            window.reply_delay.plus.click()
            if abs(window.reply_delay.value() - 3.1) > 0.001:
                raise RuntimeError('Decimal input step failed.')
            if not window.grab().save(str(target.with_suffix('.png'))):
                raise RuntimeError('Window rendering failed.')
            window.close()
            window = None
            report['checks']['qt_window_render_and_controls'] = True
        report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if window is not None:
            window.close()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            return 2
    return 0 if report['success'] else 1
