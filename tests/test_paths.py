import unittest
from pathlib import Path
from app.settings import data_root, RESOURCE_ROOT


class PathTests(unittest.TestCase):
    def test_source_preserves_existing_project_storage(self):
        self.assertEqual(data_root(frozen=False, environ={}), RESOURCE_ROOT)

    def test_exe_uses_permanent_local_appdata_not_extraction_folder(self):
        self.assertEqual(data_root(frozen=True, environ={'LOCALAPPDATA': r'C:\Users\test\AppData\Local'}),
                         Path(r'C:\Users\test\AppData\Local') / 'TelegramGuiTool')

    def test_explicit_storage_override_applies_to_both_modes(self):
        for frozen in (True, False):
            self.assertEqual(data_root(frozen=frozen, environ={'TGNL_DATA_DIR': r'C:\test\portable'}),
                             Path(r'C:\test\portable').resolve())
