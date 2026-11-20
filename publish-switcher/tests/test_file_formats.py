import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Engine, Source, SyncError, load_profile, read_json, scan
from file_formats import DEFAULT_EXTENSIONS, NO_EXTENSION, inventory, normalize_extensions
from generate import generate


class FileFormatTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get('PUBLISH_SWITCHER_TEST_TMP', str(Path(__file__).parent / '.tmp')))
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.original = self.base / 'original'
        self.target = self.base / 'publish'
        self.repo = self.base / 'repo'
        self.original.mkdir()
        self.target.mkdir()
        guard = patch('core.assert_stopped')
        guard.start()
        self.addCleanup(guard.stop)

    def write(self, directory, path, raw):
        file = directory / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)

    def build(self, **kwargs):
        generate(self.original, self.repo, 'rk', 'RK', '1', **kwargs)
        source = Source(local=self.repo)
        return source, load_profile(source, read_json(self.repo / 'catalog.json')['profiles'][0])

    def test_inventory_counts_remote_files_and_normalizes_case(self):
        self.write(self.original, 'fonts/中文.TTF', b'\x00\x01font')
        self.write(self.original, 'fonts/another.ttf', b'other')
        self.write(self.original, 'AIotApp', b'executable')
        self.write(self.original, 'driver.so', b'library')
        _, manifest = self.build()
        rows = {r['extension']: r for r in inventory(manifest)}
        self.assertEqual(rows['.ttf']['count'], 2)
        self.assertEqual(rows['.ttf']['bytes'], 11)
        self.assertEqual(rows['.ttf']['unavailable'], 0)
        self.assertEqual(rows[NO_EXTENSION]['count'], 1)
        self.assertEqual(rows['.so']['unavailable'], 1)
        self.assertEqual(normalize_extensions(' .TTF,.json,.ttf '), ('.json', '.ttf'))
        self.assertEqual(normalize_extensions(), DEFAULT_EXTENSIONS)
        for invalid in (['*.ttf'], ['../ttf'], ['.t/ttf'], [1], '.ttf,'):
            with self.assertRaises(ValueError):
                normalize_extensions(invalid)

    def test_fonts_download_cache_strict_and_restore_recorded_scope(self):
        self.write(self.original, 'fonts/new.TTF', b'\x00\x01newfont')
        self.write(self.original, 'fonts/old.ttf', b'\x00\x01replacement')
        self.write(self.target, 'fonts/old.ttf', b'\x00\x01original')
        self.write(self.target, 'fonts/extra.ttf', b'extra')
        self.write(self.target, 'main.py', b'local python')
        self.write(self.target, 'driver.so', b'untouched')
        source, manifest = self.build()
        engine = Engine(self.target, extensions=['.ttf'])
        preview = engine.preview(manifest, mode='incremental')
        self.assertEqual(preview['changes'], [('新增', 'fonts/new.TTF')])
        engine.apply(manifest, source, mode='incremental')
        self.assertEqual((self.target / 'fonts/old.ttf').read_bytes(), b'\x00\x01original')
        self.assertTrue((self.target / 'fonts/extra.ttf').exists())
        engine.apply(manifest, source, mode='strict')
        self.assertFalse((self.target / 'fonts/extra.ttf').exists())
        self.assertEqual(read_json(engine.current)['extensions'], ['.ttf'])
        # Changed preferences must not change which formats the backup restores.
        Engine(self.target, extensions=['.py']).restore()
        self.assertEqual((self.target / 'fonts/old.ttf').read_bytes(), b'\x00\x01original')
        self.assertTrue((self.target / 'fonts/extra.ttf').exists())
        self.assertEqual((self.target / 'main.py').read_bytes(), b'local python')
        self.assertEqual((self.target / 'driver.so').read_bytes(), b'untouched')
        engine.restore()
        with patch.object(source, 'download', side_effect=AssertionError('must reuse cache')):
            (self.target / 'fonts/new.TTF').unlink()
            self.assertEqual(engine.preview(manifest)['download_bytes'], 0)
            engine.apply(manifest, source)
        self.assertEqual((self.target / 'fonts/new.TTF').read_bytes(), b'\x00\x01newfont')

    def test_only_font_added_to_empty_target_can_be_restored_and_redone(self):
        self.write(self.original, 'sample.ttf', b'\x00\x01font')
        source, manifest = self.build()
        engine = Engine(self.target, extensions=['.ttf'])
        engine.apply(manifest, source)
        engine.restore()
        self.assertFalse((self.target / 'sample.ttf').exists())
        engine.restore()
        self.assertEqual((self.target / 'sample.ttf').read_bytes(), b'\x00\x01font')

    def test_strict_can_remove_local_only_selected_format_when_remote_has_none(self):
        self.write(self.original, 'main.py', b'python')
        self.write(self.target, 'obsolete.ttf', b'old font')
        self.write(self.target, 'main.py', b'local script')
        source, manifest = self.build()
        engine = Engine(self.target, extensions=['.ttf'])
        self.assertEqual(engine.preview(manifest, mode='incremental')['changes'], [])
        self.assertEqual(engine.preview(manifest)['changes'], [('删除', 'obsolete.ttf')])
        engine.apply(manifest, source)
        self.assertFalse((self.target / 'obsolete.ttf').exists())
        self.assertEqual((self.target / 'main.py').read_bytes(), b'local script')
        engine.restore()
        self.assertEqual((self.target / 'obsolete.ttf').read_bytes(), b'old font')

    def test_arbitrary_selected_format_and_unselected_resources_are_preserved(self):
        for name in ('main.py', 'active.json', 'font.ttf', 'more.otf', 'AIotApp'):
            self.write(self.original, name, b'remote')
            self.write(self.target, name, b'local')
        self.write(self.target, 'extra.otf', b'extra')
        source, manifest = self.build(extensions=['.otf', NO_EXTENSION])
        engine = Engine(self.target, extensions=['.otf', NO_EXTENSION])
        engine.apply(manifest, source)
        self.assertFalse((self.target / 'extra.otf').exists())
        self.assertEqual((self.target / 'more.otf').read_bytes(), b'remote')
        self.assertEqual((self.target / 'AIotApp').read_bytes(), b'remote')
        for name in ('main.py', 'active.json', 'font.ttf'):
            self.assertEqual((self.target / name).read_bytes(), b'local')

    def test_empty_font_metadata_only_and_no_selection_block_apply(self):
        self.write(self.original, 'font.ttf', b'font')
        self.write(self.original, 'more.otf', b'font-otf')
        source, manifest = self.build()
        self.assertIn('至少勾选', Engine(self.target, extensions=[]).preview(manifest)['blocker'])
        self.assertIn('仅记录了元数据', Engine(self.target, extensions=['.otf']).preview(manifest)['blocker'])
        font = next(e for e in manifest['entries'] if e['path'] == 'font.ttf')
        font['size'] = 0
        self.assertIn('为空', Engine(self.target).preview(manifest)['blocker'])
        with self.assertRaises(SyncError):
            Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), {})

    def test_download_integrity_failure_keeps_original_fonts(self):
        self.write(self.original, 'font.ttf', b'new-font')
        self.write(self.target, 'font.ttf', b'old-font')
        source, manifest = self.build()
        entry = next(e for e in manifest['entries'] if e['path'] == 'font.ttf')
        (self.repo / entry['source']).write_bytes(b'corrupt')
        old = scan(self.target)
        with self.assertRaises(SyncError):
            Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), old)

    def test_legacy_backup_restores_only_python_and_json(self):
        self.write(self.original, 'main.py', b'remote')
        self.write(self.target, 'main.py', b'old')
        self.write(self.target, 'font.ttf', b'font')
        source, manifest = self.build()
        engine = Engine(self.target, extensions=['.py', '.json'])
        engine.apply(manifest, source)
        data = read_json(engine.current)
        data.pop('extensions')
        engine.current.write_text(json.dumps(data), encoding='utf-8')
        (self.target / 'font.ttf').write_bytes(b'changed after update')
        Engine(self.target).restore()
        self.assertEqual((self.target / 'main.py').read_bytes(), b'old')
        self.assertEqual((self.target / 'font.ttf').read_bytes(), b'changed after update')
