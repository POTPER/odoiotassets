import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detect_screen
import detector


MONITORS = [{'left': -640, 'top': 0, 'width': 1280, 'height': 480},
            {'left': 0, 'top': 0, 'width': 640, 'height': 480},
            {'left': -640, 'top': 0, 'width': 640, 'height': 480}]


class OfflineDependencyTests(unittest.TestCase):
    def test_missing_wheel_has_copy_instructions(self):
        missing = ModuleNotFoundError("No module named 'mss'", name='mss')
        with patch.object(detect_screen.importlib, 'import_module', side_effect=missing), \
                patch.object(detect_screen, 'BUNDLED_MSS', Path('/nonexistent/mss.whl')):
            with self.assertRaisesRegex(RuntimeError, 'vendor'):
                detect_screen.load_mss()

    def test_corrupt_wheel_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'corrupt.whl'
            path.write_bytes(b'corrupt download')
            missing = ModuleNotFoundError("No module named 'mss'", name='mss')
            with patch.object(detect_screen.importlib, 'import_module', side_effect=missing), \
                    patch.object(detect_screen, 'BUNDLED_MSS', path):
                with self.assertRaisesRegex(RuntimeError, '校验失败'):
                    detect_screen.load_mss()

    def test_other_import_errors_are_not_hidden(self):
        missing = ModuleNotFoundError("No module named 'another_dependency'", name='another_dependency')
        with patch.object(detect_screen.importlib, 'import_module', side_effect=missing):
            with self.assertRaises(ModuleNotFoundError):
                detect_screen.load_mss()


class ScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)
        self.args = detect_screen.parse_args(['--once', '--output', str(self.output)])
        self.capture = Mock(monitors=MONITORS)
        self.capture.grab.side_effect = lambda region: np.full(
            (region['height'], region['width'], 4), (10, 20, 30, 255), dtype=np.uint8)
        module = types.ModuleType('mss')
        module.mss = Mock(return_value=self.capture)
        self.engine = Mock(labels=['Harness', 'Helmet'], model_path=Path('mock.rknn'),
                           last_timing={'total_ms': 15.0}, last_output_shapes=[[1, 6, 8400]],
                           last_output_format='ultralytics_raw')
        self.engine.predict.return_value = [detector.Detection((100, 100, 200, 300), .9, 0),
                                            detector.Detection((100, 50, 200, 100), .99, 1)]
        self.factory = Mock(return_value=self.engine)
        for patcher in (patch.dict(os.environ, {'DISPLAY': ':0', 'XDG_SESSION_TYPE': 'x11'}, clear=True),
                        patch.object(detect_screen.platform, 'system', return_value='Linux'),
                        patch.dict(sys.modules, {'mss': module}),
                        patch.object(detector, 'Detector', self.factory),
                        patch.object(cv2, 'VideoCapture', side_effect=AssertionError('不能打开摄像头'))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_capture_only_harness_and_save_result_without_camera(self):
        report = detect_screen.run(self.args)
        self.assertEqual(report['source_type'], 'screen')
        self.assertEqual(report['harness_count'], 1)
        self.assertEqual(report['detections'][0]['screen_box'], [100, 100, 200, 300])
        saved = list(self.output.glob('*.json'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(json.loads(saved[0].read_text(encoding='utf-8')), report)
        self.assertTrue(saved[0].with_suffix('.jpg').is_file())
        self.engine.close.assert_called_once()
        self.capture.close.assert_called_once()

    def test_bgra_to_bgr_before_inference(self):
        pixels = []

        def predict(frame):
            pixels.append((frame.shape, frame[200, 0].tolist()))
            return []

        self.engine.predict.side_effect = predict
        report = detect_screen.run(self.args)
        self.assertEqual(pixels, [((480, 640, 3), [10, 20, 30])])
        self.assertEqual(report['harness_count'], 0)

    def test_negative_screen_coordinates_in_region(self):
        self.args.region = [-600, 20, 300, 400]
        report = detect_screen.run(self.args)
        self.assertEqual(report['detections'][0]['box'], [100, 100, 200, 300])
        self.assertEqual(report['detections'][0]['screen_box'], [-500, 120, -400, 320])

    def test_out_of_bounds_region_releases_capture_before_model_load(self):
        self.args.region = [600, 0, 100, 100]
        with self.assertRaisesRegex(ValueError, '超出桌面范围'):
            detect_screen.run(self.args)
        self.capture.close.assert_called_once()
        self.factory.assert_not_called()

    def test_model_error_releases_both_resources_and_does_not_save(self):
        self.engine.predict.side_effect = RuntimeError('模拟NPU错误')
        with self.assertRaisesRegex(RuntimeError, 'NPU错误'):
            detect_screen.run(self.args)
        self.capture.close.assert_called_once()
        self.engine.close.assert_called_once()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_list_monitors_does_not_load_model_or_capture_pixels(self):
        self.args.list_monitors = True
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(detect_screen.run(self.args))
        self.assertIn('left=-640', output.getvalue())
        self.factory.assert_not_called()
        self.capture.grab.assert_not_called()

    def test_wayland_is_rejected_even_with_xwayland_display(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}):
            with self.assertRaisesRegex(RuntimeError, 'Wayland'):
                detect_screen.run(self.args)
        self.factory.assert_not_called()

    def test_missing_display_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'DISPLAY'):
                detect_screen.run(self.args)

    def test_frame_limit_stops_continuous_capture(self):
        self.args.once, self.args.max_frames, self.args.interval = False, 2, 0.0
        report = detect_screen.run(self.args)
        self.assertEqual(report['frame_index'], 2)
        self.assertEqual(self.engine.predict.call_count, 2)


if __name__ == '__main__':
    unittest.main()
