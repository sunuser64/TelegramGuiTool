"""Native Qt interface, shared by the application and visual smoke checks."""
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QSize, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QPlainTextEdit, QProgressBar,
    QFrame, QDoubleSpinBox, QScrollArea, QBoxLayout, QSizePolicy, QListView,
    QStyle, QStyleOptionComboBox, QStylePainter, QToolButton, QAbstractSpinBox,
)


STYLE = '''
QMainWindow, QWidget#workspace { background: #f2f5fa; color: #17283f; }
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #17283f; }
QFrame#hero { background: #14263e; border-radius: 16px; }
QLabel#brand { color: white; font-size: 25px; font-weight: 700; }
QLabel#subtitle { color: #b8c9dd; font-size: 13px; }
QLabel#statusBadge { color: #b7ecf3; background: #254157; border-radius: 12px; padding: 7px 14px; }
QFrame[card='true'] { background: white; border: 1px solid #e1e8f1; border-radius: 12px; }
QLabel[heading='true'] { font-size: 15px; font-weight: 600; }
QLabel[muted='true'] { color: #758499; }
QLabel[metric='true'] { font-size: 26px; font-weight: 700; }
QLabel#errorsValue { color: #ca4a59; }
QLineEdit, QComboBox, QDoubleSpinBox { background: #f8fafd; border: 1px solid #d9e2ed; border-radius: 7px; padding: 7px 9px; min-height: 19px; selection-background-color: #c7e9fa; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid #269bc6; background: white; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { color: #9cabbc; background: #f4f6fa; }
QDoubleSpinBox QLineEdit { background: transparent; border: none; padding: 0; min-height: 0; }
QToolButton[stepButton='true'] { color: #426582; background: #eaf2f9; border: 1px solid #d9e4ef; border-radius: 5px; padding: 0; font-size: 17px; min-width: 0; min-height: 0; }
QToolButton[stepButton='true']:hover { background: #d7eaf7; border-color: #a9cee4; }
QToolButton[stepButton='true']:pressed { background: #bfddf0; }
QToolButton[stepButton='true']:disabled { color: #b2bfcd; background: #f1f4f8; border-color: #e7edf4; }
QComboBox { padding-right: 42px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 34px; border-left: 1px solid #dce5ef; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: #eef4fa; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 14px; height: 14px; }
QComboBox::drop-down:hover { background: #deedf7; }
QComboBox:disabled::drop-down { background: #f1f4f8; }
QPushButton { background: #edf3f9; border: 1px solid #dce5f0; border-radius: 7px; padding: 8px 14px; font-weight: 600; min-height: 19px; }
QPushButton:hover { background: #e0ecf7; border-color: #b6cde3; }
QPushButton:pressed { background: #cfe0ef; }
QPushButton#startButton { color: white; background: #168eb6; border-color: #168eb6; }
QPushButton#startButton:hover { background: #087b9f; }
QPushButton#stopButton { color: #b74454; background: #fff2f3; border-color: #f1d5da; }
QPushButton:disabled, QPushButton#startButton:disabled, QPushButton#stopButton:disabled { color: #a0adbd; background: #f1f4f8; border-color: #e7ecf3; }
QPlainTextEdit { background: #f8fafd; border: 1px solid #e3eaf3; border-radius: 8px; padding: 8px; selection-background-color: #c7e9fa; }
QPlainTextEdit#activityLog { color: #bbcddd; background: #172a40; border: none; font-family: Consolas; font-size: 12px; }
QProgressBar { border: none; border-radius: 5px; background: #e9eff6; min-height: 11px; max-height: 11px; }
QProgressBar::chunk { background: #24a6c9; border-radius: 5px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QComboBox QAbstractItemView { background: white; color: #17283f; border: 1px solid #cad9e8; border-radius: 8px; padding: 5px; outline: 0; selection-background-color: #e1eff8; selection-color: #123f5c; }
QComboBox QAbstractItemView::item { min-height: 32px; padding: 5px 9px; border-radius: 5px; }
QComboBox QAbstractItemView::item:hover { background: #edf6fc; }
QScrollArea { border: none; background: #f2f5fa; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #9fb1c4; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


class ModeSelect(QComboBox):
    """Elide selected text before the arrow; use the same styled popup on Windows."""
    aboutToOpen = Signal()
    def __init__(self):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(0)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        view = QListView()
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        self.currentTextChanged.connect(self.setToolTip)

    def minimumSizeHint(self):
        return QSize(100, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight,
                                                         max(0, rect.width() - 4))
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def showPopup(self):
        self.aboutToOpen.emit()
        super().showPopup()
        self.view().window().setFixedWidth(self.width())


class StepInput(QDoubleSpinBox):
    """Decimal input with clear +/- buttons that do not select the edited text."""
    def __init__(self):
        super().__init__()
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setSingleStep(0.1)
        self.setDecimals(2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lineEdit().setTextMargins(0, 0, 0, 0)
        self.minus = QToolButton(self)
        self.plus = QToolButton(self)
        for button, text, direction in ((self.minus, '−', -1), (self.plus, '+', 1)):
            button.setText(text)
            button.setProperty('stepButton', True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoRepeat(True)
            button.setAccessibleName('Уменьшить на 0,1 секунды' if direction < 0 else 'Увеличить на 0,1 секунды')
            button.clicked.connect(lambda checked=False, step=direction: self.stepBy(step))
        self.valueChanged.connect(self.update_step_buttons)
        self.update_step_buttons()

    def minimumSizeHint(self):
        return QSize(140, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_controls()

    def place_controls(self):
        if hasattr(self, 'minus'):
            self.lineEdit().setGeometry(10, 1, max(1, self.width() - 84), max(1, self.height() - 2))
            top = max(0, (self.height() - 26) // 2)
            self.minus.setGeometry(self.width() - 64, top, 26, 26)
            self.plus.setGeometry(self.width() - 34, top, 26, 26)
            self.minus.raise_()
            self.plus.raise_()

    def stepBy(self, steps):
        super().stepBy(steps)
        self.lineEdit().deselect()
        self.lineEdit().setCursorPosition(len(self.lineEdit().text()))
        self.update_step_buttons()

    def update_step_buttons(self):
        if hasattr(self, 'minus'):
            self.place_controls()
            flags = self.stepEnabled()
            self.minus.setEnabled(self.isEnabled() and bool(flags & QAbstractSpinBox.StepEnabledFlag.StepDownEnabled))
            self.plus.setEnabled(self.isEnabled() and bool(flags & QAbstractSpinBox.StepEnabledFlag.StepUpEnabled))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.update_step_buttons()


class FlexibleLabel(QLabel):
    def minimumSizeHint(self):
        # A long filename/status must not force the entire scroll content wider.
        return QSize(0, super().minimumSizeHint().height())


class ResponsiveWorkspace(QWidget):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.adapt(event.size().width())
        return super().eventFilter(watched, event)

    def adapt(self, width):
        if not hasattr(self, 'columns'):
            return
        mode = (width < 900, width < 640, width < 780, width < 850)
        if mode == getattr(self, '_mode', None):
            return
        self._mode = mode
        narrow, compact, wrap_buttons, stack_header = mode
        self.columns.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self.metrics.setDirection(QBoxLayout.Direction.LeftToRight)
        for row in (self.file_row, self.options_row):
            row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.hero_layout.setDirection(QBoxLayout.Direction.TopToBottom if stack_header else QBoxLayout.Direction.LeftToRight)
        self.log_header.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        while self.buttons.count():
            self.buttons.takeAt(0)
        for column in range(5):
            self.buttons.setColumnStretch(column, 0)
        if wrap_buttons:
            for index, button in enumerate(self.control_buttons[:4]):
                self.buttons.addWidget(button, index // 2, index % 2)
            self.buttons.addWidget(self.control_buttons[4], 2, 0, 1, 2)
            self.buttons.setColumnStretch(0, 1)
            self.buttons.setColumnStretch(1, 1)
        else:
            for column, button in enumerate(self.control_buttons):
                self.buttons.addWidget(button, 0, column)
                self.buttons.setColumnStretch(column, 1)
        margin = 12 if compact else 24
        self.layout().setContentsMargins(margin, 16, margin, 16)
        self.layout().invalidate()
        self.updateGeometry()


def label(text, *, heading=False, muted=False):
    result = FlexibleLabel(text)
    result.setProperty('heading', heading)
    result.setProperty('muted', muted)
    result.setWordWrap(True)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setMinimumWidth(0)
    result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return result


def card(title=None):
    frame = QFrame()
    frame.setProperty('card', True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title:
        layout.addWidget(label(title, heading=True))
    return frame, layout


def build_interface(window):
    window.setWindowTitle('Telegram GUI Tool')
    window.resize(1080, 900)
    window.setMinimumSize(480, 420)
    chevron = (Path(__file__).parent / 'assets' / 'chevron-down.svg').as_posix()
    window.setStyleSheet(STYLE.replace('@CHEVRON@', chevron))
    root = ResponsiveWorkspace()
    root.setObjectName('workspace')
    root.setMinimumWidth(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    window.setCentralWidget(scroll)
    window.workspace = root
    window.workspace_scroll = scroll
    layout = QVBoxLayout(root)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(12)

    hero = QFrame()
    hero.setObjectName('hero')
    hero_layout = QHBoxLayout(hero)
    root.hero_layout = hero_layout
    hero_layout.setContentsMargins(22, 14, 22, 14)
    titles = QVBoxLayout()
    brand = label('Telegram / Workspace')
    brand.setObjectName('brand')
    titles.addWidget(brand)
    subtitle = label('Сообщения из TXT · ответы · сохранённый прогресс')
    subtitle.setObjectName('subtitle')
    titles.addWidget(subtitle)
    hero_layout.addLayout(titles, 3)
    window.status_badge = label('Готов к работе')
    window.status_badge.setObjectName('statusBadge')
    hero_layout.addWidget(window.status_badge, 1)
    layout.addWidget(hero)

    metrics = QHBoxLayout()
    root.metrics = metrics
    for attribute, title, object_name in (
        ('total_value', 'ЗАПИСЕЙ В ОЧЕРЕДИ', 'totalValue'),
        ('completed_value', 'ВЫПОЛНЕНО', 'completedValue'),
        ('errors_value', 'ОШИБОК', 'errorsValue'),
    ):
        frame, inner = card()
        inner.addWidget(label(title, muted=True))
        value = label('0')
        value.setProperty('metric', True)
        value.setObjectName(object_name)
        inner.addWidget(value)
        setattr(window, attribute, value)
        metrics.addWidget(frame)
    layout.addLayout(metrics)

    columns = QHBoxLayout()
    root.columns = columns
    columns.setSpacing(14)
    source, source_layout = card('01  Исходные данные')
    file_row = QHBoxLayout()
    root.file_row = file_row
    window.path = QLineEdit()
    window.path.setReadOnly(True)
    window.path.setMinimumWidth(0)
    window.path.setPlaceholderText('TXT — одна строка на сообщение')
    window.choose = QPushButton('Выбрать TXT')
    file_row.addWidget(window.path, 1)
    file_row.addWidget(window.choose)
    source_layout.addLayout(file_row)
    window.remove_empty = QCheckBox('Пропускать пустые строки')
    window.remove_empty.setChecked(True)
    window.cancel_load = QPushButton('Отменить загрузку')
    options_row = QHBoxLayout()
    root.options_row = options_row
    options_row.addWidget(window.remove_empty, 1)
    options_row.addWidget(window.cancel_load)
    source_layout.addLayout(options_row)
    window.file_info = label('Файл ещё не выбран', muted=True)
    window.file_info.setWordWrap(True)
    source_layout.addWidget(window.file_info)
    window.preview = QPlainTextEdit()
    window.preview.setReadOnly(True)
    window.preview.setPlaceholderText('Предпросмотр первых 10 строк\nПри запуске программы это поле очищается.')
    window.preview.setMinimumHeight(105)
    window.preview.setFixedHeight(130)
    source_layout.addWidget(window.preview, 1)
    columns.addWidget(source, 1)

    settings, settings_layout = card('02  Параметры обработки')
    window.mode = ModeSelect()
    window.mode.addItems(['Локальный тест', 'Проверка окна Telegram', 'Отправка TXT и чтение ответов'])
    window.mode.setCurrentIndex(2)
    settings_layout.addWidget(window.mode)
    window.username = QLineEdit()
    window.username.setPlaceholderText('@username получателя')
    settings_layout.addWidget(window.username)
    hint = label('Откройте переписку вручную. Получатель проверяется при запуске.', muted=True)
    hint.setWordWrap(True)
    settings_layout.addWidget(hint)
    timing = QGridLayout()
    timing.addWidget(label('До чтения ответа, с', muted=True), 0, 0)
    timing.addWidget(label('После чтения, с', muted=True), 0, 1)
    window.reply_delay = StepInput()
    window.reply_delay.setRange(0, 3600)
    window.reply_delay.setValue(3)
    window.inter_message_delay = StepInput()
    window.inter_message_delay.setRange(0, 3600)
    window.inter_message_delay.setValue(2)
    timing.addWidget(window.reply_delay, 1, 0)
    timing.addWidget(window.inter_message_delay, 1, 1)
    settings_layout.addLayout(timing)
    jitter_row = QHBoxLayout()
    jitter_row.addWidget(label('Разброс задержек ±, с', muted=True))
    window.delay_jitter = StepInput()
    window.delay_jitter.setRange(0, 60)
    window.delay_jitter.setValue(0)
    window.delay_jitter.setToolTip('Например 0,20: задержка 2 с меняется от 1,8 до 2,2 с. 0 — без разброса.')
    jitter_row.addWidget(window.delay_jitter)
    settings_layout.addLayout(jitter_row)
    settings_layout.addWidget(label('Отправка  →  ожидание  →  чтение  →  следующая строка', muted=True))
    settings_layout.addStretch()
    columns.addWidget(settings, 1)
    layout.addLayout(columns, 2)

    controls, controls_layout = card('03  Управление очередью')
    buttons = QGridLayout()
    root.buttons = buttons
    window.start = QPushButton('Начать')
    window.start.setObjectName('startButton')
    window.pause = QPushButton('Пауза')
    window.pause.setToolTip('Приостановить перед следующим действием в Telegram')
    window.resume = QPushButton('Продолжить')
    window.resume.setToolTip('Продолжить очередь. Для возврата в Telegram даётся 5 секунд')
    window.stop = QPushButton('Остановить')
    window.stop.setToolTip('Прервать ожидание и сохранить состояние очереди')
    window.stop.setObjectName('stopButton')
    window.export = QPushButton('Экспорт JSON')
    root.control_buttons = (window.start, window.pause, window.resume, window.stop, window.export)
    controls_layout.addLayout(buttons)
    window.current = label('Текущая задача: —', muted=True)
    window.counters = label('', muted=True)
    window.counters.setWordWrap(True)
    controls_layout.addWidget(window.current)
    window.progress = QProgressBar()
    window.progress.setTextVisible(False)
    controls_layout.addWidget(window.progress)
    controls_layout.addWidget(window.counters)
    layout.addWidget(controls)

    log_header = QHBoxLayout()
    root.log_header = log_header
    log_header.addWidget(label('Журнал выполнения', heading=True), 1)
    log_header.addWidget(label('Содержимое сообщений в журнал не записывается', muted=True), 2)
    layout.addLayout(log_header)
    window.logs = QPlainTextEdit()
    window.logs.setObjectName('activityLog')
    window.logs.setReadOnly(True)
    window.logs.setFixedHeight(140)
    window.logs.document().setMaximumBlockCount(2000)
    layout.addWidget(window.logs, 1)
    root.adapt(450)
    scroll.setWidget(root)
    scroll.viewport().installEventFilter(root)
    root.adapt(scroll.viewport().width())
