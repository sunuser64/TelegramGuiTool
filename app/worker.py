import logging
import threading
import time
from contextlib import nullcontext
from PySide6.QtCore import QThread, Signal
from .file_manager import load_txt, LoadCancelled
from .parser import fixture_message, parse_message
from .ui_controller import TelegramController, UIStateError
from .exporter import export_run
from .chat_controller import TelegramChat, ExchangeError
from .timing import varied_delay

logger = logging.getLogger(__name__)


class FileWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, path, remove_empty, database=None):
        super().__init__()
        self.path, self.remove_empty = path, remove_empty
        self.database = database
        self.cancel_event = threading.Event()

    def run(self):
        try:
            result = load_txt(self.path, self.remove_empty, self.cancel_event.is_set)
            if self.cancel_event.is_set():
                raise LoadCancelled()
            run_id = self.database.create_run(result.lines, self.cancel_event.is_set) if self.database else None
            self.loaded.emit((result, run_id))
        except LoadCancelled:
            self.cancelled.emit()
        except Exception:
            logger.exception('Ошибка загрузки TXT')
            self.failed.emit('Не удалось прочитать TXT. Проверьте доступ, кодировку и формат файла.')


class ExportWorker(QThread):
    notice = Signal(str)

    def __init__(self, database, run_id, path):
        super().__init__()
        self.database, self.run_id, self.path = database, run_id, path

    def run(self):
        try:
            export_run(self.database, self.run_id, self.path)
            self.notice.emit('JSON-отчёт сохранён.')
        except Exception:
            logger.exception('Ошибка экспорта JSON')
            self.notice.emit('Не удалось записать JSON. Проверьте доступ и место на диске.')


class TestWorker(QThread):
    progress = Signal()
    current = Signal(int)
    notice = Signal(str)
    outcome = Signal(str)

    def __init__(self, database, run_id, inspect_telegram=False, username=None,
                 reply_delay=3, inter_message_delay=2, delay_jitter=0):
        super().__init__()
        self.database, self.run_id = database, run_id
        self.inspect_telegram = inspect_telegram
        self.username = username
        self.reply_delay, self.inter_message_delay = reply_delay, inter_message_delay
        self.delay_jitter = delay_jitter
        self.stop_event = threading.Event()
        self.condition = threading.Condition()
        self.paused = False
        self.pause_acknowledged = False

    def pause(self):
        with self.condition:
            self.paused = True
            self.condition.notify_all()

    def resume(self):
        with self.condition:
            self.paused = False
            self.condition.notify_all()

    def stop(self):
        self.stop_event.set()
        self.resume()

    def ui_checkpoint(self):
        with self.condition:
            if self.paused and not self.stop_event.is_set():
                if not self.pause_acknowledged:
                    self.database.set_run_status(self.run_id, 'paused')
                    self.pause_acknowledged = True
                    self.notice.emit('Обработка на паузе. Действия в Telegram приостановлены.')
                    self.progress.emit()
                while self.paused and not self.stop_event.is_set():
                    self.condition.wait()
            if self.stop_event.is_set():
                raise UIStateError('Остановлено пользователем.')
            if self.pause_acknowledged:
                self.pause_acknowledged = False
                self.database.set_run_status(self.run_id, 'running')
                self.progress.emit()

    def wait_between_iterations(self, delay):
        remaining = delay
        while remaining > 0 and not self.stop_event.is_set():
            try:
                self.ui_checkpoint()
            except UIStateError:
                if self.stop_event.is_set():
                    return
                raise
            started = time.monotonic()
            with self.condition:
                self.condition.wait_for(lambda: self.paused or self.stop_event.is_set(), timeout=remaining)
            remaining = max(0, remaining - (time.monotonic() - started))

    def run(self):
        try:
            chat = TelegramChat(self.username, self.stop_event, reply_delay=self.reply_delay,
                                checkpoint=self.ui_checkpoint, delay_jitter=self.delay_jitter) if self.username else None
            with chat.session() if chat else nullcontext():
                if chat:
                    self.notice.emit('Проверка уже открытой переписки в Telegram…')
                    chat.prepare_open_chat()
                self.process_queue(chat)
        except Exception as exc:
            # Never log unknown UIA exception contents, which may contain chat text.
            self.notice.emit(str(exc) if isinstance(exc, UIStateError) else 'Не удалось открыть чат Telegram.')
            try:
                self.database.set_run_status(self.run_id, 'stopped')
            except Exception:
                logger.exception('Не удалось сохранить остановку')
            self.progress.emit()
            self.outcome.emit('stopped')

    def process_queue(self, chat=None):
        status = 'stopped'
        try:
            self.database.set_run_status(self.run_id, 'running')
            while not self.stop_event.is_set():
                try:
                    self.ui_checkpoint()
                except UIStateError:
                    if self.stop_event.is_set():
                        break
                    raise
                if self.stop_event.is_set():
                    break
                self.database.set_run_status(self.run_id, 'running')
                task = self.database.claim(self.run_id)
                if task is None:
                    status = 'finished'
                    break
                self.current.emit(task['id'])
                try:
                    if chat:
                        spread = f' ± {self.delay_jitter:g}' if self.delay_jitter else ''
                        self.notice.emit(f'Задача №{task["id"]}: отправка → ожидание {self.reply_delay:g}{spread} с → чтение.')
                        result = chat.exchange(task['input'], lambda value: self.database.save_processing_result(task['id'], value))
                        self.notice.emit(f'Задача №{task["id"]}: сохранено сообщений — {len(result["messages"])}.')
                    else:
                        result = parse_message(fixture_message(task['input']))
                    if self.inspect_telegram and not chat:
                        result['telegram'] = TelegramController(checkpoint=self.ui_checkpoint).inspect()
                    self.database.finish_task(task['id'], 'completed', result=result)
                except UIStateError as exc:
                    if self.stop_event.is_set() and (not isinstance(exc, ExchangeError) or not exc.result.get('send_attempted')):
                        self.database.return_unsent_task(task['id'])
                        self.notice.emit('Остановка до отправки. Запись возвращена в оставшуюся очередь.')
                        break
                    self.database.finish_task(task['id'], 'failed',
                                              result=exc.result if isinstance(exc, ExchangeError) else None,
                                              error=str(exc))
                    self.notice.emit(str(exc))
                    # Unexpected UI state stops the entire GUI inspection run.
                    logger.warning('Telegram task stopped id=%s reason=%s', task['id'], str(exc))
                    break
                except Exception:
                    if chat:
                        # Unknown send outcome must never trigger another send or task.
                        self.notice.emit('Ошибка сохранения или обмена. Очередь остановлена; проверьте последний результат.')
                        raise
                    logger.exception('Ошибка обработки задачи id=%s', task['id'])
                    self.database.finish_task(task['id'], 'failed', error='Ошибка обработки задачи.')
                    self.notice.emit(f'Ошибка задачи №{task["id"]}; обработка продолжается.')
                self.progress.emit()
                actual_delay = varied_delay(self.inter_message_delay, self.delay_jitter) if chat else 0.12
                if chat:
                    self.notice.emit(f'Ожидание {actual_delay:g} с перед следующей итерацией.')
                self.wait_between_iterations(actual_delay)
            self.database.set_run_status(self.run_id, status)
        except Exception:
            logger.exception('Ошибка фоновой обработки')
            status = 'interrupted'
            try:
                self.database.set_run_status(self.run_id, status)
            except Exception:
                logger.exception('Не удалось сохранить статус запуска')
            self.notice.emit('Обработка прервана. Проверьте доступ к SQLite и журнал.')
        finally:
            self.progress.emit()
            self.outcome.emit(status)
