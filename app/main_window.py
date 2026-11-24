import logging
from datetime import datetime
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QFileDialog, QMessageBox
from .worker import FileWorker, TestWorker, ExportWorker
from .settings import ROOT
from .chat_controller import normalize_username
from .interface import build_interface

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, database):
        super().__init__()
        self.database = database
        self.run_id = database.recover()
        self.worker = None
        self.loader = None
        self.exporter = None
        self.closing = False
        self.pending_action = None
        self.queued_file = None
        build_interface(self)
        self.mode.aboutToOpen.connect(self.prepare_mode_change)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.choose.clicked.connect(self.select_file)
        self.cancel_load.clicked.connect(self.cancel_loading)
        self.start.clicked.connect(self.begin)
        self.pause.clicked.connect(self.pause_run)
        self.resume.clicked.connect(self.resume_run)
        self.stop.clicked.connect(self.stop_run)
        self.export.clicked.connect(self.export_results)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dispatch_pending)
        self.refresh()
        if self.run_id:
            options = self.database.options(self.run_id)
            if options:
                self.username.setText(options['username'])
                self.reply_delay.setValue(options['reply_delay'])
                self.inter_message_delay.setValue(options['inter_message_delay'])
                self.delay_jitter.setValue(options['delay_jitter'])
            self.log(f'Восстановлена очередь №{self.run_id}. Нажмите «Продолжить» для оставшихся задач.')
            snapshot = self.database.summary(self.run_id)
            self.file_info.setText(f'Восстановлено записей: {snapshot["total"]}; исходный TXT не требуется.')

    def log(self, message):
        self.logs.appendPlainText(f'{datetime.now():%H:%M:%S}  {message}')

    def busy(self):
        return self.timer.isActive() or bool(self.worker and self.worker.isRunning())

    def refresh(self):
        try:
            snapshot = self.database.summary(self.run_id) if self.run_id else {}
            total = snapshot.get('total', 0)
            completed = snapshot.get('completed', 0)
            failed = snapshot.get('failed', 0)
            skipped = snapshot.get('skipped', 0)
            done = completed + failed + skipped
            pending = snapshot.get('pending', 0)
            self.total_value.setText(str(total))
            self.completed_value.setText(str(completed))
            self.errors_value.setText(str(failed))
            self.progress.setValue(round(done * 100 / total) if total else 0)
            self.counters.setText(f'Обработано {done} из {total}  ·  {self.progress.value()}%'
                                  + (f'  ·  Пропущено: {skipped}' if skipped else ''))
            busy = self.busy()
            loading = self.loader is not None
            self.choose.setEnabled(not loading)
            self.remove_empty.setEnabled(not busy and not loading)
            self.cancel_load.setEnabled(loading and not self.loader.cancel_event.is_set())
            self.start.setEnabled(not busy and not loading and pending > 0)
            self.mode.setEnabled(not loading)
            self.username.setEnabled(not busy and self.mode.currentIndex() == 2)
            timings_enabled = not busy and self.mode.currentIndex() == 2
            self.reply_delay.setEnabled(timings_enabled)
            self.inter_message_delay.setEnabled(timings_enabled)
            self.delay_jitter.setEnabled(timings_enabled)
            paused = bool(self.worker and self.worker.paused)
            stopping = bool(self.worker and self.worker.stop_event.is_set())
            self.pause.setEnabled(busy and not self.timer.isActive() and not paused and not stopping)
            self.resume.setEnabled(not self.timer.isActive() and not loading and not stopping
                                   and ((busy and paused) or (not busy and pending > 0)))
            self.stop.setEnabled(busy and not stopping)
            self.export.setEnabled(self.run_id is not None and self.exporter is None)
            if stopping:
                state = 'Остановка…'
            elif self.timer.isActive():
                state = 'Переключитесь в Telegram · 5 с'
            elif paused:
                state = 'Пауза' if self.worker.pause_acknowledged else 'Пауза запрошена…'
            elif busy:
                state = 'Обработка'
            elif loading:
                state = 'Загрузка TXT'
            else:
                state = {'finished': 'Завершено', 'stopped': 'Остановлено', 'interrupted': 'Можно продолжить'}.get(
                    snapshot.get('status'), 'Готов к работе')
            self.status_badge.setText(state)
        except Exception:
            logger.exception('Ошибка чтения состояния SQLite')
            self.log('Не удалось обновить состояние SQLite.')

    def select_file(self):
        if self.busy() or self.worker is not None:
            self.stop_run()
        path, _ = QFileDialog.getOpenFileName(self, 'Открыть TXT', str(ROOT / 'data'), 'Текст (*.txt)')
        if path:
            self.load_file(path)

    def load_file(self, path):
        if self.worker is not None:
            self.queued_file = path
            self.stop_run()
            self.log('Новый TXT будет загружен после сохранения текущей операции.')
            return
        if self.timer.isActive():
            self.stop_run()
        if self.loader is not None:
            return
        self.loader = FileWorker(path, self.remove_empty.isChecked(), self.database)
        self.loader.loaded.connect(self.file_loaded)
        self.loader.failed.connect(self.log)
        self.loader.cancelled.connect(lambda: self.log('Загрузка отменена. Предыдущая очередь сохранена.'))
        self.loader.finished.connect(self.loading_finished)
        self.loader.start()
        self.refresh()

    def mode_changed(self, index):
        if self.busy() or self.worker is not None:
            self.stop_run()
            self.log('Остановка текущей обработки. Выбранный режим будет использован при следующем запуске.')
        self.refresh()

    def prepare_mode_change(self):
        if self.busy() or self.worker is not None:
            self.stop_run()
            self.log('Остановка обработки для выбора нового режима.')

    def cancel_loading(self):
        if self.loader:
            self.loader.cancel_event.set()
            self.refresh()

    def file_loaded(self, payload):
        loaded, run_id = payload
        if self.closing or self.loader.cancel_event.is_set():
            return
        try:
            self.run_id = run_id
            self.path.setText(loaded.path)
            self.path.setToolTip(loaded.path)
            self.path.setCursorPosition(0)
            self.file_info.setText(f'Записей: {len(loaded.lines)} | Кодировка: {loaded.encoding}')
            self.preview.setPlainText('\n'.join(loaded.lines[:10]))
            self.log(f'Создан запуск №{self.run_id}; записей: {len(loaded.lines)}.')
            self.refresh()
        except Exception:
            logger.exception('Ошибка создания очереди')
            self.log('Не удалось сохранить очередь в SQLite.')

    def loading_finished(self):
        self.loader.deleteLater()
        self.loader = None
        self.refresh()
        if self.closing:
            self.close()

    def begin(self):
        if self.busy() or self.run_id is None:
            return
        mode = ('local', 'inspect', 'chat')[self.mode.currentIndex()]
        target = ''
        if mode == 'chat':
            try:
                target = normalize_username(self.username.text())
            except ValueError as exc:
                QMessageBox.warning(self, 'Username', str(exc))
                return
        try:
            options = self.database.options(self.run_id)
            if options and options['mode'] != mode:
                self.run_id = self.database.clone_pending(self.run_id)
                self.log('Для нового режима создана очередь из оставшихся записей. Старые результаты сохранены.')
                self.refresh()
                if not self.database.summary(self.run_id)['pending']:
                    self.log('Оставшихся записей нет. Выберите TXT для нового запуска.')
                    return
        except Exception:
            logger.exception('Не удалось подготовить очередь нового режима')
            self.log('Не удалось подготовить очередь. Проверьте доступ к SQLite.')
            return
        text = ('Запустить обработку локальных фиктивных ответов?'
                if self.mode.currentIndex() == 0 else
                'Запустить локальный тест и чтение UI Telegram? После подтверждения '
                'переключитесь в Telegram за 5 секунд. Тексты чатов не сохраняются; сообщения не отправляются.')
        if mode == 'chat':
            timing_text = (f'Отправка → ожидание {self.reply_delay.value():g} с → чтение ответов '
                           f'→ ожидание {self.inter_message_delay.value():g} с → следующая строка')
            if self.delay_jitter.value():
                timing_text += f'. Разброс каждой задержки: ±{self.delay_jitter.value():g} с'
            text = (f'Отправить оставшиеся строки TXT в чат @{target}? Каждая строка — отдельное сообщение. '
                    f'Будут сохранены новые входящие ответы. {timing_text}. '
                    'Заранее откройте нужную переписку в развёрнутом Telegram, '
                    'затем переключитесь в него за 5 секунд. Поиск и переключение чатов не выполняются. '
                    'Подтверждайте только для согласованного тестового чата.')
        if QMessageBox.question(self, 'Подтверждение запуска', text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.database.bind_options(self.run_id, mode, target, reply_delay=self.reply_delay.value(),
                                       inter_message_delay=self.inter_message_delay.value(), delay_jitter=self.delay_jitter.value())
        except Exception as exc:
            QMessageBox.warning(self, 'Параметры запуска', str(exc))
            return
        if self.mode.currentIndex() in (1, 2):
            self.log('Старт через 5 секунд. Переключитесь в Telegram.')
            self.pending_action = 'start'
            self.timer.start(5000)
            self.refresh()
        else:
            self.launch_worker()

    def dispatch_pending(self):
        action = self.pending_action
        self.pending_action = None
        if action == 'resume':
            if self.worker and not self.worker.stop_event.is_set():
                self.worker.resume()
                self.log('Обработка продолжена.')
            self.refresh()
        elif action == 'start':
            self.launch_worker()

    def launch_worker(self):
        if self.worker is not None:
            return
        self.pending_action = None
        try:
            options = self.database.options(self.run_id)
        except Exception:
            logger.exception('Не удалось прочитать параметры запуска')
            self.log('Запуск отменён: не удалось прочитать настройки SQLite.')
            self.refresh()
            return
        self.worker = TestWorker(self.database, self.run_id, self.mode.currentIndex() == 1,
                                 username=options['username'] if options and options['mode'] == 'chat' else None,
                                 **{key: options[key] for key in ('reply_delay', 'inter_message_delay', 'delay_jitter')} if options else {})
        self.worker.progress.connect(self.refresh)
        self.worker.notice.connect(self.log)
        self.worker.current.connect(lambda task_id: self.current.setText(f'Текущая задача: №{task_id}'))
        self.worker.outcome.connect(lambda status: self.log(f'Обработка завершена: {status}.'))
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()
        self.log('Тест запущен пользователем.')
        self.refresh()

    def worker_finished(self):
        self.timer.stop()
        self.pending_action = None
        self.worker.deleteLater()
        self.worker = None
        self.current.setText('Текущая задача: —')
        self.refresh()
        if self.closing:
            self.close()
        elif self.queued_file:
            path, self.queued_file = self.queued_file, None
            self.load_file(path)

    def pause_run(self):
        if self.worker and not self.worker.stop_event.is_set():
            self.worker.pause()
            self.log('Пауза запрошена. Перед следующим действием в Telegram обработка приостановится.')
            self.refresh()

    def resume_run(self):
        if self.timer.isActive():
            return
        if not self.worker:
            self.begin()
            return
        if not self.worker.paused or self.worker.stop_event.is_set():
            return
        if self.mode.currentIndex() in (1, 2):
            self.pending_action = 'resume'
            self.timer.start(5000)
            self.log('Продолжение через 5 секунд. Переключитесь в Telegram.')
        else:
            self.worker.resume()
            self.log('Обработка продолжена.')
        self.refresh()

    def stop_run(self):
        self.timer.stop()
        self.pending_action = None
        if self.worker:
            self.worker.stop()
        elif self.run_id is not None:
            try:
                self.database.set_run_status(self.run_id, 'stopped')
            except Exception:
                logger.exception('Не удалось сохранить остановку отсчёта')
        self.log('Остановка запрошена. Незавершённая очередь сохранена.')
        self.refresh()

    def export_results(self):
        if self.run_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт JSON',
                    str(ROOT / 'exports' / f'run_{self.run_id}.json'), 'JSON (*.json)')
        if path:
            self.exporter = ExportWorker(self.database, self.run_id, path)
            self.exporter.notice.connect(self.log)
            self.exporter.finished.connect(self.export_finished)
            self.exporter.start()
            self.refresh()

    def export_finished(self):
        self.exporter.deleteLater()
        self.exporter = None
        self.refresh()
        if self.closing:
            self.close()

    def closeEvent(self, event):
        if self.busy() or self.loader or self.exporter:
            self.closing = True
            self.timer.stop()
            self.pending_action = None
            if self.worker:
                self.worker.stop()
            if self.loader:
                self.loader.cancel_event.set()
            event.ignore()
            if not self.worker and not self.loader and not self.exporter:
                QTimer.singleShot(0, self.close)
        else:
            event.accept()
