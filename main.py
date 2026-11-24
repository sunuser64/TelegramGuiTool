import logging
import sys
import os
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from app.settings import configure_logging, DB_PATH
from app.database import Database
from app.main_window import MainWindow


def main():
    if '--self-test' in sys.argv:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from app.diagnostics import self_test
        return self_test(sys.argv)
    application = QApplication(sys.argv)
    application.setStyle('Fusion')
    application.setFont(QFont('Segoe UI', 10))
    try:
        configure_logging()
        lock = QLockFile(str(DB_PATH.parent / 'app.lock'))
        if not lock.tryLock(0):
            QMessageBox.warning(None, 'Приложение уже запущено',
                                'Другой экземпляр использует эту очередь или папка data недоступна.')
            return 1
        window = MainWindow(Database(DB_PATH))
    except Exception:
        logging.exception('Не удалось инициализировать приложение')
        QMessageBox.critical(None, 'Ошибка запуска', 'Проверьте доступ к папкам data и logs и базе progress.db.')
        return 1
    window.show()
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
