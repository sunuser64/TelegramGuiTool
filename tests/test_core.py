import json
from pathlib import Path
import tempfile
import unittest
from app.file_manager import load_txt, LoadCancelled
from app.parser import fixture_message, parse_message
from app.database import Database
from app.exporter import export_run


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def txt(self, data):
        path = self.root / 'input.txt'
        path.write_bytes(data)
        return path

    def test_supported_encodings_and_unchanged_original(self):
        for encoding in ('utf-8', 'utf-8-sig', 'cp1251'):
            with self.subTest(encoding=encoding):
                data = 'тест_001\r\n\r\n  \r\ntest_002\r\n'.encode(encoding)
                path = self.txt(data)
                loaded = load_txt(path)
                self.assertEqual(loaded.encoding, encoding)
                self.assertEqual(loaded.lines, ['тест_001', 'test_002'])
                self.assertEqual(path.read_bytes(), data)

    def test_preserve_empty_lines_and_whitespace(self):
        self.assertEqual(load_txt(self.txt(b' first \n\n \nlast'), False).lines,
                         [' first ', '', ' ', 'last'])

    def test_empty_file_count(self):
        self.assertEqual(len(load_txt(self.txt(b'')).lines), 0)

    def test_binary_and_unsupported_encoding(self):
        for data in (b'abc\0def', b'\x98', b'\xef\xbb\xbf\xff', b'\x01abc'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_txt(self.txt(data))

    def test_load_cancellation(self):
        with self.assertRaises(LoadCancelled):
            load_txt(self.txt(b'test'), cancelled=lambda: True)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_txt(self.root / 'missing.txt')

    def test_parser(self):
        self.assertEqual(parse_message(fixture_message('тест')),
                         {'messages': ['Test response: тест']})

    def test_parser_rejects_invalid_payload(self):
        for message in ('not json', '[]', '{}',
                        '{"type":"test_response","messages":[]}',
                        '{"type":"test_response","messages":[123]}'):
            with self.subTest(message=message), self.assertRaises(ValueError):
                parse_message(message)

    def database(self):
        return Database(self.root / 'progress.db')

    def test_statuses_and_counters(self):
        db = self.database()
        run_id = db.create_run(['one', 'two', 'three'])
        for status in ('completed', 'failed', 'skipped'):
            task = db.claim(run_id)
            self.assertEqual(task['status'], 'processing')
            db.finish_task(task['id'], status, result={'messages': ['ok']} if status == 'completed' else None)
        self.assertIsNone(db.claim(run_id))
        result = db.summary(run_id)
        self.assertEqual((result['total'], result['completed'], result['failed'], result['skipped']), (3, 1, 1, 1))

    def test_recovery_does_not_repeat_completed_or_failed(self):
        db = self.database()
        run_id = db.create_run(['one', 'two', 'three'])
        db.finish_task(db.claim(run_id)['id'], 'completed', {'messages': ['ok']})
        db.finish_task(db.claim(run_id)['id'], 'failed', error='test error')
        pending_id = db.claim(run_id)['id']
        db.set_run_status(run_id, 'running')
        reopened = self.database()
        self.assertEqual(reopened.recover(), run_id)
        self.assertEqual(reopened.summary(run_id)['status'], 'interrupted')
        self.assertEqual(reopened.claim(run_id)['id'], pending_id)
        self.assertIsNone(reopened.claim(run_id))

    def test_cancelled_import_rolls_back(self):
        db = self.database()
        with self.assertRaises(LoadCancelled):
            db.create_run(['one', 'two'], cancelled=lambda: True)
        self.assertIsNone(db.recover())

    def test_illegal_transition(self):
        db = self.database()
        run_id = db.create_run(['one'])
        task_id = db.snapshot(run_id)['records'][0]['id']
        with self.assertRaises(ValueError):
            db.finish_task(task_id, 'completed')
        db.claim(run_id)
        with self.assertRaises(ValueError):
            db.finish_task(task_id, 'pending')
        db.finish_task(task_id, 'completed')
        with self.assertRaises(ValueError):
            db.finish_task(task_id, 'completed')

    def test_export_intermediate_unicode_and_final(self):
        db = self.database()
        run_id = db.create_run(['тест', 'two'])
        db.finish_task(db.claim(run_id)['id'], 'completed', {'messages': ['Ответ']})
        path = self.root / 'report.json'
        export_run(db, run_id, path)
        raw = path.read_text(encoding='utf-8')
        self.assertIn('Ответ', raw)
        report = json.loads(raw)
        self.assertEqual(report['run_id'], run_id)
        self.assertEqual(report['completed'], 1)
        self.assertEqual(report['records'][1]['status'], 'pending')
        db.finish_task(db.claim(run_id)['id'], 'completed')
        db.set_run_status(run_id, 'finished')
        export_run(db, run_id, path)
        self.assertIsNotNone(json.loads(path.read_text(encoding='utf-8'))['finished_at'])
        self.assertIsNone(db.recover())

    def test_bad_export_path(self):
        db = self.database()
        with self.assertRaises(OSError):
            export_run(db, db.create_run(['one']), self.root / 'missing' / 'out.json')

    def test_sql_inputs_are_data(self):
        db = self.database()
        text = "'); DROP TABLE tasks; --"
        run_id = db.create_run([text])
        self.assertEqual(db.preview(run_id), [text])


if __name__ == '__main__':
    unittest.main()
