import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher_settings_store as store
from launcher_install import install
from launcher_runtime import load_settings
from core import SyncError, read_json


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.publish = self.base / 'publish'
        self.publish.mkdir()
        self.path = self.base / 'settings/settings.json'
        self.original = {'publish_dir': str(self.publish), 'collection_enabled': False, 'theme': 'dark',
                         'results_dir': str(self.base / '桌面/成果输出'), 'future': {'preserve': '中文'}}

    def test_last_successful_settings_are_backed_up_and_corruption_is_preserved(self):
        store.write_settings(self.path, self.original)
        changed = dict(self.original, theme='light', submission_enabled=True, submission_dir=str(self.base / 'submission'))
        store.write_settings(self.path, changed)
        corrupted = b'{"broken":"incomplete'
        self.path.write_bytes(corrupted)
        with self.assertLogs('launcher_settings_store', level='WARNING'):
            self.assertEqual(load_settings(self.path), changed)
        self.assertEqual(read_json(self.path), changed)
        self.assertEqual(read_json(store.backup_path(self.path)), changed)
        preserved = list(self.path.parent.glob('settings.json.corrupt-*'))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), corrupted)

    def test_existing_valid_settings_get_a_backup_and_missing_primary_is_restored(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(self.original), encoding='utf-8')
        self.assertEqual(load_settings(self.path), self.original)
        self.assertEqual(read_json(store.backup_path(self.path)), self.original)
        self.path.unlink()
        with self.assertLogs('launcher_settings_store', level='WARNING'):
            self.assertEqual(load_settings(self.path), self.original)
        self.assertEqual(read_json(self.path), self.original)

    def test_invalid_schema_and_encoding_use_valid_backup(self):
        store.write_settings(self.path, self.original)
        for raw in (b'[]', b'{"publish_dir":""}', b'\xff\xfe\x00'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertLogs('launcher_settings_store', level='WARNING'):
                    self.assertEqual(load_settings(self.path), self.original)

    def test_reinstall_with_explicit_publish_repairs_settings_without_valid_backup(self):
        self.path.parent.mkdir()
        corrupt = b'{broken'
        self.path.write_bytes(corrupt)
        store.backup_path(self.path).write_bytes(b'also broken')
        with self.assertRaisesRegex(SyncError, '实际publish路径'):
            load_settings(self.path)
        self.assertEqual(self.path.read_bytes(), corrupt)
        with self.assertLogs('launcher_settings_store', level='WARNING'):
            install(self.publish, config_dir=self.path.parent, applications=self.base / 'apps')
        repaired = load_settings(self.path)
        self.assertEqual(repaired['publish_dir'], str(self.publish))
        self.assertIs(repaired['collection_enabled'], False)
        self.assertIs(repaired['submission_enabled'], False)
        self.assertTrue(any(file.read_bytes() == corrupt for file in self.path.parent.glob('settings.json.corrupt-*')))
        self.assertEqual(read_json(store.backup_path(self.path)), repaired)

    def test_backup_write_failure_does_not_falsely_report_primary_settings_as_unsaved(self):
        store.write_settings(self.path, self.original)
        changed = dict(self.original, theme='light')
        original_write = store.atomic_json
        def fail_backup(path, data):
            if Path(path) == store.backup_path(self.path):
                raise PermissionError('backup denied')
            return original_write(path, data)
        with patch('launcher_settings_store.atomic_json', side_effect=fail_backup), self.assertLogs('launcher_settings_store', level='WARNING'):
            store.write_settings(self.path, changed)
        self.assertEqual(read_json(self.path), changed)
        self.assertEqual(read_json(store.backup_path(self.path)), self.original)
        self.assertEqual(load_settings(self.path), changed)
        self.assertEqual(read_json(store.backup_path(self.path)), changed)

    def test_failed_primary_write_keeps_original_and_backup(self):
        store.write_settings(self.path, self.original)
        with patch('launcher_settings_store.atomic_json', side_effect=PermissionError()), self.assertRaises(PermissionError):
            store.write_settings(self.path, dict(self.original, theme='light'))
        self.assertEqual(read_json(self.path), self.original)
        self.assertEqual(read_json(store.backup_path(self.path)), self.original)


if __name__ == '__main__':
    unittest.main()
