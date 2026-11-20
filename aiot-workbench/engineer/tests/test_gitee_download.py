import base64
import hashlib
import json
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Cancelled, Engine, Source, SyncError, scan
from gitee_download import MAX_BLOB_FILE_BYTES
from test_network import response
import test_sync


class GiteeDownloadTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def remote_source(self):
        return Source(owner='example', repo='repo', commit='a' * 40, provider='gitee')

    @staticmethod
    def git_sha(payload):
        return hashlib.sha1(('blob {}\0'.format(len(payload))).encode() + payload).hexdigest()

    def blob(self, payload):
        return {'sha': self.git_sha(payload), 'size': len(payload), 'encoding': 'base64',
                'content': base64.b64encode(payload).decode('ascii')}

    @staticmethod
    def forbidden():
        return urllib.error.HTTPError('https://gitee.com/example/repo/raw/file', 403, 'Forbidden', {}, None)

    def test_raw_403_uses_official_blob_and_preserves_binary_bytes(self):
        payload = b'\x00\x01\x00\xff\r\n' * 100
        source = self.remote_source()
        dest = self.base / 'Font.ttf'
        progress = []
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(self.blob(payload)).encode())]
            source.download('publish_RK/中文/Font.ttf', dest, len(payload), 'git:' + self.git_sha(payload), None, progress.append)
            self.assertEqual(opener.return_value.open.call_count, 2)
            url = opener.return_value.open.call_args[0][0].full_url
            self.assertEqual(url, source.api_base + '/git/blobs/' + self.git_sha(payload))
        self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(sum(progress), len(payload))
        self.assertFalse(list(self.base.glob('*.part-*')))

    def test_sha256_catalog_resolves_blob_from_exact_commit(self):
        payload = b'font binary'
        source = self.remote_source()
        tree = {'truncated': False, 'tree': [{'path': 'publish_RK/font.ttf', 'mode': '100644',
                'type': 'blob', 'size': len(payload), 'sha': self.git_sha(payload)}]}
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(tree).encode()),
                                                    response(json.dumps(self.blob(payload)).encode())]
            source.download('publish_RK/font.ttf', self.base / 'font.ttf', len(payload), hashlib.sha256(payload).hexdigest(), None, lambda n: None)
            urls = [call.args[0].full_url for call in opener.return_value.open.call_args_list]
        self.assertEqual(urls[1], source.tree_url())
        self.assertIn('a' * 40, urls[1])

    def test_invalid_or_truncated_api_content_never_replaces_destination(self):
        payload = b'whole font'
        cases = [dict(sha='b' * 40), dict(size=len(payload) - 1), dict(encoding='utf-8'),
                 dict(content='invalid!'), dict(content=base64.b64encode(payload[:-1]).decode()),
                 dict(content=base64.b64encode(b'x' * len(payload)).decode())]
        dest = self.base / 'font.ttf'
        dest.write_bytes(b'old cache')
        for mutation in cases:
            with self.subTest(mutation=mutation), patch('core.urllib.request.build_opener') as opener:
                blob = dict(self.blob(payload), **mutation)
                opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(blob).encode())]
                with self.assertRaises(SyncError):
                    self.remote_source().download('font.ttf', dest, len(payload), 'git:' + self.git_sha(payload), None, lambda n: None)
            self.assertEqual(dest.read_bytes(), b'old cache')
            self.assertFalse(list(self.base.glob('*.part-*')))

    def test_api_access_denial_is_reported_without_more_attempts(self):
        with patch('core.urllib.request.build_opener') as opener, patch('core.retry_pause') as pause:
            opener.return_value.open.side_effect = [self.forbidden(), self.forbidden()]
            with self.assertRaisesRegex(SyncError, '官方 Blob API.*HTTP 403'):
                self.remote_source().download('font.ttf', self.base / 'font.ttf', 10, 'git:' + 'b' * 40, None, lambda n: None)
            self.assertEqual(opener.return_value.open.call_count, 2)
            pause.assert_not_called()

    def test_external_and_github_403_never_use_gitee_fallback(self):
        for source, location in ((self.remote_source(), 'https://example.com/file.ttf?secret=hidden'),
                                 (Source(owner='example', repo='repo', commit='a' * 40), 'font.ttf')):
            with self.subTest(location=location), patch('core.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = self.forbidden()
                with self.assertRaisesRegex(SyncError, 'HTTP 403') as error:
                    source.download(location, self.base / 'font.ttf', 10, 'git:' + 'b' * 40, None, lambda n: None)
                self.assertNotIn('secret=hidden', str(error.exception))
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_fallback_is_bounded_and_cancelled_download_cannot_commit(self):
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.forbidden()
            with self.assertRaisesRegex(SyncError, '64 MiB'):
                self.remote_source().download('large.ttf', self.base / 'font.ttf', MAX_BLOB_FILE_BYTES + 1,
                                       'git:' + 'b' * 40, None, lambda n: None)
            self.assertEqual(opener.return_value.open.call_count, 1)
        payload = b'font'
        cancel = threading.Event()
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(self.blob(payload)).encode())]
            with self.assertRaises(Cancelled):
                self.remote_source().download('font.ttf', self.base / 'font.ttf', len(payload), 'git:' + self.git_sha(payload),
                                       cancel, lambda n: cancel.set())
        self.assertFalse((self.base / 'font.ttf').exists())
        self.assertFalse(list(self.base.glob('*.part-*')))

    def test_engine_caches_verified_blob_for_identical_font_paths(self):
        payload = b'\x00\x01font'
        sha = self.git_sha(payload)
        manifest = {'schema_version': 1, 'id': 'rk', 'version': '1', 'entries': [
            {'type': 'file', 'path': name, 'mode': '0644', 'size': len(payload), 'git_sha1': sha,
             'source': 'publish_RK/' + name} for name in ('font1.ttf', 'font2.ttf')]}
        engine = Engine(self.target, extensions=['.ttf'])
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(self.blob(payload)).encode())]
            engine.apply(manifest, self.remote_source())
            self.assertEqual(opener.return_value.open.call_count, 2)
        for name in ('font1.ttf', 'font2.ttf'):
            self.assertEqual((self.target / name).read_bytes(), payload)
        self.assertEqual(engine.preview(manifest)['download_bytes'], 0)

    def test_failed_blob_validation_keeps_original_publish(self):
        payload = b'complete font'
        manifest = {'schema_version': 1, 'id': 'rk', 'version': '1', 'entries': [
            {'type': 'file', 'path': 'font.ttf', 'mode': '0644', 'size': len(payload),
             'git_sha1': self.git_sha(payload), 'source': 'publish_RK/font.ttf'}]}
        before = scan(self.target)
        blob = self.blob(payload)
        blob['content'] = base64.b64encode(payload[:3]).decode()
        with patch('core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [self.forbidden(), response(json.dumps(blob).encode())]
            with self.assertRaises(SyncError):
                Engine(self.target).apply(manifest, self.remote_source())
        self.assertEqual(scan(self.target), before)
