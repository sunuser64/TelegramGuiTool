"""Telegram Desktop UIA exchange. No API login and no blind keyboard sending."""
import ctypes
import re
import time
import logging
import unicodedata
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from .ui_controller import TelegramController, UIStateError
from .timing import varied_delay

logger = logging.getLogger(__name__)


def uia_diagnostic(exc):
    # Exception messages can contain chat text. Retain only a type and error code.
    code = getattr(exc, 'hresult', None)
    return type(exc).__name__ + (f' HRESULT={code}' if isinstance(code, int) else '')


def normalize_username(value):
    value = value.strip().removeprefix('@')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', value):
        raise ValueError('Укажите username: латинские буквы, цифры, подчёркивание; без ссылки и пробелов.')
    return value.lower()


@dataclass(frozen=True)
class Message:
    key: tuple
    text: str
    incoming: bool


def message_signature(message):
    # UIA row IDs can be recreated or reused as Telegram updates its list.
    # Compare chronological content; keep original response text in the export.
    text = unicodedata.normalize('NFC', message.text.replace('\r\n', '\n').replace('\r', '\n')).strip()
    return message.incoming, text


def new_outgoing_positions(before, after, sent_text):
    previous = [message_signature(message) for message in before]
    current = [message_signature(message) for message in after]
    target = message_signature(Message((), sent_text, False))
    # The loaded history normally appends rows and may evict an old prefix.
    for overlap in range(min(len(previous), len(current)), 0, -1):
        if previous[-overlap:] == current[:overlap]:
            return [index for index in range(overlap, len(current)) if current[index] == target]
    # No sequence overlap: accept only an increased occurrence count, never an
    # arbitrary historical row with matching text or a changed UIA runtime ID.
    old_count = Counter(previous)[target]
    positions = [index for index, signature in enumerate(current) if signature == target]
    return positions[old_count:]


class ExchangeError(UIStateError):
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


class TelegramChat(TelegramController):
    def __init__(self, username, stop_event, reply_delay=3, checkpoint=None, delay_jitter=0):
        super().__init__()
        self.username = normalize_username(username)
        self.stop_event = stop_event
        if not 0 <= reply_delay <= 3600:
            raise ValueError('Задержка перед чтением: 0–3600 с.')
        self.reply_delay = reply_delay
        if not 0 <= delay_jitter <= 60:
            raise ValueError('Разброс задержек: 0–60 с.')
        self.delay_jitter = delay_jitter
        self.window = None
        self.chat_confirmed = False
        self.checkpoint = checkpoint

    @contextmanager
    def session(self):
        status = ctypes.windll.ole32.CoInitializeEx(None, 0)
        if status not in (0, 1):
            raise UIStateError('Не удалось инициализировать Windows UI Automation.')
        try:
            self.chat_confirmed = False
            self.window = self._active_window()
            yield self
        except UIStateError:
            raise
        except Exception:
            # UIA errors can contain message text; do not propagate them to logs.
            raise UIStateError('Ошибка Telegram UI Automation. Очередь остановлена; проверьте состояние окна.') from None
        finally:
            self.chat_confirmed = False
            ctypes.windll.ole32.CoUninitialize()

    def guard(self, dialogs=False):
        if self.checkpoint:
            self.checkpoint()
        if self.stop_event.is_set():
            raise UIStateError('Остановлено пользователем.')
        window = self.window
        if ctypes.windll.user32.GetForegroundWindow() != window.handle:
            # A click on Pause/Stop moves focus before Qt delivers its button slot.
            # Give that control request a brief chance to reach the worker.
            self.stop_event.wait(0.2)
            if self.checkpoint:
                self.checkpoint()
            if self.stop_event.is_set():
                raise UIStateError('Остановлено пользователем.')
            if ctypes.windll.user32.GetForegroundWindow() != window.handle:
                raise UIStateError('Фокус Telegram потерян; очередь остановлена.')
        if not window.is_enabled() or not window.is_visible():
            raise UIStateError('Окно Telegram изменилось или недоступно.')
        self._check_dialog(window)
        # Qt layer dialogs may lack WindowPattern. Block them structurally.
        for item in window.descendants() if dialogs else ():
            if item.is_visible():
                self._check_dialog(item)
                classes = item.element_info.automation_id.split('.')
                # BoxContentDivider is a normal profile separator, not a dialog.
                # Match whole class tokens in the overlay layer, never substrings.
                if ('class Ui::LayerStackWidget' in classes
                        and 'class Ui::BoxContent' in classes):
                    raise UIStateError('Открыт Qt-диалог Telegram (LayerStackWidget / BoxContent). Закройте его вручную.')
        return window

    def elements(self, kind=None, marker=None, names=None):
        self.guard()
        return [item for item in self.window.descendants()
                if item.is_visible() and item.is_enabled()
                and (kind is None or item.element_info.control_type == kind)
                and (marker is None or marker in item.element_info.automation_id)
                and (names is None or item.window_text().casefold() in {name.casefold() for name in names})]

    def unique(self, **criteria):
        items = self.elements(**criteria)
        if len(items) != 1:
            raise UIStateError('Нужный элемент Telegram не найден однозначно. Разверните окно и проверьте язык интерфейса (RU/EN).')
        return items[0]

    def click(self, element):
        from pywinauto.uia_defines import NoPatternInterfaceError
        self.guard(dialogs=True)
        try:
            element.iface_invoke.Invoke()
        except NoPatternInterfaceError:
            # Coordinates derive from a freshly found UIA element, never a fixed point.
            self.guard()
            element.click_input()

    def wait(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.guard()
            value = predicate()
            if value:
                return value
            self.stop_event.wait(0.25)
        raise UIStateError('Таймаут поиска элемента Telegram. Очередь остановлена.')

    def editor(self):
        return self._inner_editor('HistoryView::ChatWidget')

    def _inner_editor(self, marker):
        candidates = [e for e in self.elements(kind='Edit', marker=marker)
                      if e.element_info.automation_id.endswith('class Ui::InputField::Inner')]
        if len(candidates) != 1:
            raise UIStateError('Поле ввода Telegram недоступно или неоднозначно.')
        return candidates[0]

    def set_value(self, element, value):
        self.guard()
        element.iface_value.SetValue(value)
        if element.iface_value.CurrentValue != value:
            raise UIStateError('Telegram не подтвердил введённый текст.')
        self.move_caret_to_end(element)

    def move_caret_to_end(self, element):
        from pywinauto.uia_defines import NoPatternInterfaceError
        from comtypes import COMError
        self.guard()
        element.set_focus()
        self.guard()
        try:
            text_range = element.iface_text.DocumentRange
            # TextPattern endpoints: Start=0, End=1. Collapse at the document end.
            text_range.MoveEndpointByRange(0, text_range, 1)
            text_range.Select()
        except (NoPatternInterfaceError, COMError):
            # Qt builds without a selectable TextPattern use a guarded key chord.
            self.guard()
            if not element.has_keyboard_focus():
                raise UIStateError('Поле ввода не получило фокус; курсор не перемещён.')
            element.type_keys('^{END}', set_foreground=False)

    def verify_username(self):
        # Exact value next to the Username label inside the visible profile.
        labels = [item for item in self.elements(kind='Text', marker='Info::Profile::InnerWidget',
                                                names={'Username', 'Имя пользователя'})
                  if 'MainWidget.class Info::SectionWidget' in item.element_info.automation_id]
        for label in labels:
            values = [e.window_text().strip().lower() for e in label.parent().parent().descendants()
                      if e.is_visible() and e.element_info.control_type == 'Text']
            if '@' + self.username in values:
                return True
        return False

    def verify_chat(self):
        self.guard()
        # Recipient is confirmed once by prepare_open_chat for this session.
        # Iterations check the active Telegram window, never its caption/profile.
        if not self.chat_confirmed:
            raise UIStateError('Открытая переписка ещё не проверена перед запуском.')

    def prepare_open_chat(self):
        """Inspect the user's current conversation; never search or select a chat."""
        self.chat_confirmed = False
        self.guard(dialogs=True)
        editor = self.editor()
        if editor.iface_value.CurrentValue:
            raise UIStateError('В чате есть черновик. Сохраните или очистите его вручную.')
        if not self.verify_username():
            info = self.unique(kind='Button', marker='HistoryView::TopBarWidget', names={'Info', 'Информация'})
            self.click(info)
            try:
                self.wait(self.verify_username)
            except UIStateError:
                self.guard()  # Preserve a focus-loss or stop reason, if applicable.
                raise UIStateError('Username открытой переписки не подтверждён. Проверьте получателя '
                                   'и откройте его боковой профиль в развёрнутом Telegram.') from None
        self.chat_confirmed = True
        # A narrow Telegram may show a profile overlay covering the composer.
        # Refuse it rather than closing the identity panel and sending blind.
        self.read_messages()  # Validate readable message metadata before the first send.

    def read_messages(self):
        # Qt can invalidate a row while a message is appended or edited.
        # Retry reads only; outbound actions are never repeated automatically.
        for attempt in range(3):
            try:
                return self._read_messages_once()
            except UIStateError:
                raise
            except Exception as exc:
                logger.warning('UIA snapshot retry=%s diagnostic=%s', attempt + 1, uia_diagnostic(exc))
                self.guard()
                if attempt == 2:
                    raise UIStateError('Не удалось прочитать обновляющуюся историю Telegram '
                                       f'({uia_diagnostic(exc)}). Частичный ответ сохранён.') from None
                self.stop_event.wait(0.2)

    def _read_messages_once(self):
        self.guard(dialogs=True)
        self.verify_chat()
        history = self.unique(kind='List', marker='HistoryView::ListWidget')
        messages = []
        for item in history.children(control_type='ListItem'):
            fields = {}
            for child in item.children():
                name = child.window_text()
                if name in ('Message', 'Delivery', 'Time', 'Sender'):
                    fields[name] = child.iface_value.CurrentValue
            if 'Message' not in fields:
                continue  # non-text/service items cannot be returned as text replies
            direction = fields.get('Delivery', '').strip().lower()
            if direction not in ('received', 'sent', 'seen', 'delivered', 'sending',
                                 'получено', 'отправлено', 'прочитано', 'отправляется'):
                raise UIStateError('Telegram не предоставил направление сообщения; чтение остановлено.')
            runtime = tuple(item.element_info.runtime_id)
            if not runtime:
                raise UIStateError('Telegram не предоставил идентификатор сообщения.')
            # Delivery changes Sent -> Seen must not create a new message key.
            key = (runtime, fields.get('Time', ''), fields.get('Sender', ''))
            messages.append(Message(key, fields['Message'], direction in ('received', 'получено')))
        return messages

    def exchange(self, text, save_progress):
        result = {'messages': [], 'username': self.username, 'send_attempted': False,
                  'outgoing_observed': False}
        phase = 'проверка чата'
        try:
            if not text.strip() or any(ord(c) < 32 for c in text):
                raise UIStateError('Строка пуста или содержит управляющие символы; отправка запрещена.')
            self.verify_chat()
            editor = self.editor()
            if editor.iface_value.CurrentValue:
                raise UIStateError('В поле ввода уже есть черновик; отправка остановлена.')
            baseline = self.read_messages()
            phase = 'ввод строки'
            self.set_value(editor, text)
            self.verify_chat()
            button = self.unique(kind='Button', marker='HistoryView::ChatWidget',
                                 names={'Send', 'Send Message', 'Отправить', 'Отправить сообщение'})
            self.guard()
            result['send_attempted'] = True
            save_progress(dict(result))  # durable intent BEFORE any external send
            self.verify_chat()
            phase = 'нажатие отправки'
            self.click(button)
            phase = 'чтение ответа'
            return self.collect(text, baseline, result, save_progress)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, UIStateError) else f'Ошибка UI Automation: {phase} ({uia_diagnostic(exc)}).'
            logger.warning('Telegram exchange stopped phase=%s diagnostic=%s', phase, uia_diagnostic(exc))
            raise ExchangeError(reason, result) from None

    def collect(self, sent_text, baseline, result, save_progress):
        # One delay, then one snapshot. No separate collection window or idle timer.
        actual_delay = varied_delay(self.reply_delay, self.delay_jitter)
        result['reply_delay_seconds'] = actual_delay
        if self.stop_event.wait(actual_delay):
            raise UIStateError('Остановлено пользователем до чтения ответа.')
        for attempt in range(3):
            messages = self.read_messages()
            outgoing = new_outgoing_positions(baseline, messages, sent_text)
            result['confirmation'] = {'baseline_rows': len(baseline), 'current_rows': len(messages),
                                      'new_matching_outgoing': len(outgoing), 'read_attempt': attempt + 1}
            if outgoing or attempt == 2:
                break
            logger.warning('Outgoing confirmation not visible; retry read=%s rows_before=%s rows_after=%s',
                           attempt + 1, len(baseline), len(messages))
            if self.stop_event.wait(0.2):
                raise UIStateError('Остановлено пользователем во время подтверждения отправки.')
        if len(outgoing) != 1:
            raise UIStateError(f'Не удалось подтвердить новое исходящее сообщение: найдено {len(outgoing)} '
                               f'(строк истории: {len(baseline)} → {len(messages)}). Повторная отправка запрещена.')
        result['outgoing_observed'] = True
        for message in messages[outgoing[0] + 1:]:
            if message.incoming:
                result['messages'].append(message.text)
        result['reply_complete'] = False
        result['completion_reason'] = 'snapshot_after_delay'
        save_progress({**result, 'messages': list(result['messages'])})
        return result
