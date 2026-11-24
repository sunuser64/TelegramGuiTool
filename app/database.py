import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Database:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    total INTEGER NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
                    input TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
                    ('pending','processing','completed','failed','skipped')),
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS task_queue ON tasks(run_id,status,id);
                CREATE TABLE IF NOT EXISTS run_options (
                    run_id INTEGER PRIMARY KEY REFERENCES runs(id),
                    mode TEXT NOT NULL, username TEXT NOT NULL DEFAULT '');
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(run_options)')}
            for name, definition in {
                'reply_delay': 'REAL NOT NULL DEFAULT 3',
                'inter_message_delay': 'REAL NOT NULL DEFAULT 2',
                'delay_jitter': 'REAL NOT NULL DEFAULT 0',
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE run_options ADD COLUMN {name} {definition}')
            if 'reply_delay' not in columns:
                db.execute('UPDATE run_options SET reply_delay=3,inter_message_delay=2')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_run(self, lines, cancelled=lambda: False):
        with self.connect() as db:
            stamp = now()
            run_id = db.execute('INSERT INTO runs(started_at,total,status) VALUES(?,?,?)',
                                (stamp, len(lines), 'ready')).lastrowid
            def rows():
                from .file_manager import LoadCancelled
                for line in lines:
                    if cancelled():
                        raise LoadCancelled()
                    yield (run_id, line, stamp, stamp)
            db.executemany('INSERT INTO tasks(run_id,input,status,created_at,updated_at) '
                           'VALUES(?,?,\'pending\',?,?)', rows())
            if cancelled():
                from .file_manager import LoadCancelled
                raise LoadCancelled()
            return run_id

    def summary(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT runs.*, '
                "(SELECT count(*) FROM tasks WHERE run_id=runs.id AND status='pending') AS pending, "
                "(SELECT count(*) FROM tasks WHERE run_id=runs.id AND status='skipped') AS skipped "
                'FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise ValueError('Запуск не найден.')
            return dict(row)

    def preview(self, run_id):
        with self.connect() as db:
            return [row['input'] for row in db.execute(
                'SELECT input FROM tasks WHERE run_id=? ORDER BY id LIMIT 10', (run_id,))]

    def recover(self):
        with self.connect() as db:
            # A recorded send intent is ambiguous after a crash. Never resend it.
            db.execute("UPDATE tasks SET status='failed',error=?,updated_at=? "
                       "WHERE status='processing' AND result IS NOT NULL "
                       "AND json_extract(result,'$.send_attempted')=1",
                       ('Отправка могла состояться до сбоя; автоматический повтор запрещён.', now()))
            db.execute("UPDATE tasks SET status='pending',updated_at=? WHERE status='processing'", (now(),))
            db.execute("UPDATE runs SET failed=(SELECT count(*) FROM tasks WHERE run_id=runs.id AND status='failed')")
            db.execute("UPDATE runs SET status='interrupted' WHERE status IN ('running','paused')")
            row = db.execute("SELECT id FROM runs WHERE status != 'finished' ORDER BY id DESC LIMIT 1").fetchone()
            return row['id'] if row else None

    def options(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT mode,username,reply_delay,inter_message_delay,delay_jitter '
                             'FROM run_options WHERE run_id=?', (run_id,)).fetchone()
            return dict(row) if row else None

    def clone_pending(self, run_id):
        """A different mode gets a separate run; never repeat terminal tasks."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            total = db.execute("SELECT count(*) FROM tasks WHERE run_id=? AND status='pending'", (run_id,)).fetchone()[0]
            stamp = now()
            new_id = db.execute('INSERT INTO runs(started_at,total,status) VALUES(?,?,?)',
                                (stamp, total, 'ready')).lastrowid
            db.execute("INSERT INTO tasks(run_id,input,status,created_at,updated_at) "
                       "SELECT ?,input,'pending',?,? FROM tasks WHERE run_id=? AND status='pending' ORDER BY id",
                       (new_id, stamp, stamp, run_id))
            return new_id

    def bind_options(self, run_id, mode, username='', reply_delay=3, inter_message_delay=2, delay_jitter=0):
        if (not 0 <= reply_delay <= 3600 or not 0 <= inter_message_delay <= 3600
                or not 0 <= delay_jitter <= 60):
            raise ValueError('Недопустимое время ожидания или задержки.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT mode,username FROM run_options WHERE run_id=?', (run_id,)).fetchone()
            if row and (row['mode'], row['username']) != (mode, username):
                raise ValueError('Режим и получатель этого запуска уже сохранены. Загрузите TXT заново для нового запуска.')
            db.execute('INSERT OR IGNORE INTO run_options(run_id,mode,username) VALUES(?,?,?)', (run_id, mode, username))
            db.execute('UPDATE run_options SET reply_delay=?,inter_message_delay=?,delay_jitter=? WHERE run_id=?',
                       (reply_delay, inter_message_delay, delay_jitter, run_id))

    def save_processing_result(self, task_id, result):
        with self.connect() as db:
            cursor = db.execute("UPDATE tasks SET result=?,updated_at=? WHERE id=? AND status='processing'",
                                (json.dumps(result, ensure_ascii=False), now(), task_id))
            if cursor.rowcount != 1:
                raise ValueError('Задача больше не находится в обработке.')

    def return_unsent_task(self, task_id):
        with self.connect() as db:
            cursor = db.execute("UPDATE tasks SET status='pending',result=NULL,error=NULL,updated_at=? "
                                "WHERE id=? AND status='processing' AND "
                                "coalesce(json_extract(result,'$.send_attempted'),0)=0", (now(), task_id))
            if cursor.rowcount != 1:
                raise ValueError('Задачу с возможной отправкой нельзя автоматически вернуть в очередь.')

    def claim(self, run_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM tasks WHERE run_id=? AND status='pending' ORDER BY id LIMIT 1",
                             (run_id,)).fetchone()
            if row:
                db.execute("UPDATE tasks SET status='processing',updated_at=? WHERE id=?", (now(), row['id']))
                task = dict(row)
                task['status'] = 'processing'
                return task

    def finish_task(self, task_id, status, result=None, error=None):
        if status not in ('completed', 'failed', 'skipped'):
            raise ValueError('Недопустимый конечный статус.')
        with self.connect() as db:
            row = db.execute('SELECT run_id,status FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row['status'] != 'processing':
                raise ValueError('Задача не находится в обработке.')
            db.execute('UPDATE tasks SET status=?,result=?,error=?,updated_at=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                        error, now(), task_id))
            db.execute("UPDATE runs SET completed=(SELECT count(*) FROM tasks WHERE run_id=? AND status='completed'),"
                       "failed=(SELECT count(*) FROM tasks WHERE run_id=? AND status='failed') WHERE id=?",
                       (row['run_id'], row['run_id'], row['run_id']))

    def set_run_status(self, run_id, status):
        if status not in ('ready', 'running', 'paused', 'stopped', 'interrupted', 'finished'):
            raise ValueError('Неизвестный статус запуска.')
        with self.connect() as db:
            db.execute('UPDATE runs SET status=?,finished_at=? WHERE id=?',
                       (status, now() if status == 'finished' else None, run_id))

    def snapshot(self, run_id):
        with self.connect() as db:
            # Both queries use one consistent read transaction during intermediate exports.
            db.execute('BEGIN')
            run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if not run:
                raise ValueError('Запуск не найден.')
            result = dict(run)
            options = db.execute('SELECT mode,username,reply_delay,inter_message_delay,delay_jitter '
                                 'FROM run_options WHERE run_id=?', (run_id,)).fetchone()
            result['options'] = dict(options) if options else None
            result['records'] = []
            for row in db.execute('SELECT * FROM tasks WHERE run_id=? ORDER BY id', (run_id,)):
                record = dict(row)
                record['result'] = json.loads(record['result']) if record['result'] else None
                result['records'].append(record)
            return result
