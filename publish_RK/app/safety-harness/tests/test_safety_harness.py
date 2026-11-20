import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detector
import io_helpers
import safety_harness as app
import detect_image


def raw_output():
    # Helmet scores highest, but must not consume the harness max_det budget.
    return np.array([[[320, 320, 320], [320, 320, 320], [100, 100, 100],
                      [200, 200, 200], [.9, .8, .01], [.01, .01, .99]]], dtype=np.float32)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.transform = detector.Letterbox((480, 640), (480, 640), (0, 80))

    def test_raw_filters_helmet_before_nms_and_limit(self):
        result = detector.postprocess([raw_output()], self.transform, 2, max_det=1, keep_classes=[0])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].class_id, 0)
        self.assertEqual(result[0].box, (270, 140, 370, 340))

    def test_helmet_only_is_zero_harness(self):
        output = raw_output()[:, :, 2:]
        self.assertEqual(detector.postprocess([output], self.transform, 2, keep_classes=[0]), [])

    def test_end2end_filters_and_does_not_repeat_nms(self):
        output = np.array([[[270, 220, 370, 420, .9, 0],
                            [270, 220, 370, 420, .8, 0],
                            [270, 220, 370, 420, .99, 1]]], dtype=np.float32)
        result = detector.postprocess([output], self.transform, 2, keep_classes=[0])
        self.assertEqual([item.class_id for item in result], [0, 0])

    def test_rockchip_two_outputs(self):
        scores = np.array([[[.9, .01], [.01, .99]]], dtype=np.float32)
        boxes = np.array([[[270, 50], [220, 50], [370, 100], [420, 100]]], dtype=np.float32)
        result = detector.postprocess([scores, boxes], self.transform, 2, keep_classes=[0])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].box, (270, 140, 370, 340))

    def test_ambiguous_shape_requires_format(self):
        with self.assertRaisesRegex(ValueError, '歧义'):
            detector.postprocess([np.zeros((1, 6, 6), dtype=np.float32)], self.transform, 2)

    def test_integer_outputs_fail_instead_of_guessing_quantization(self):
        with self.assertRaisesRegex(ValueError, '浮点数'):
            detector.postprocess([raw_output().astype(np.int8)], self.transform, 2)

    def test_preprocessing_rgb_padding_and_geometry(self):
        frame = np.full((101, 203, 3), (10, 20, 30), dtype=np.uint8)
        data, transform = detector.preprocess(frame, (640, 640))
        self.assertEqual(data.shape, (1, 640, 640, 3))
        self.assertEqual(data.dtype, np.uint8)
        self.assertEqual(data[0, 320, 320].tolist(), [30, 20, 10])
        self.assertEqual(data[0, 0, 0].tolist(), [114, 114, 114])
        self.assertEqual(transform.original_size, (101, 203))

    def test_class_names_cannot_be_swapped_silently(self):
        app.validate_harness(['Harness', 'Helmet'], 0)
        with self.assertRaises(ValueError):
            app.validate_harness(['Harness', 'Helmet'], 1)


class FakeRKNN:
    NPU_CORE_AUTO, NPU_CORE_0, NPU_CORE_1, NPU_CORE_2, NPU_CORE_0_1_2 = range(5)
    instances = []
    output = None
    init_code = 0

    def __init__(self):
        self.released = False
        self.__class__.instances.append(self)

    def load_rknn(self, _path):
        return 0

    def init_runtime(self, **_kwargs):
        return self.init_code

    def inference(self, inputs, data_format):
        self.input_shape = inputs[0].shape
        self.input_format = data_format
        return [self.output]

    def release(self):
        self.released = True


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'test.rknn'
        self.model.write_bytes(b'mocked model; not a real RKNN')
        (self.root / 'labels.txt').write_text('Harness\nHelmet\n', encoding='utf-8')
        self.image = self.root / '测试图片.png'
        self.image.write_bytes(cv2.imencode('.png', np.zeros((480, 640, 3), dtype=np.uint8))[1].tobytes())
        self.args = app.parse_args(['--model', str(self.model), '--source', str(self.image),
                                    '--output', str(self.root / 'output')])
        FakeRKNN.instances = []
        FakeRKNN.output, FakeRKNN.init_code = raw_output(), 0
        module = types.ModuleType('rknnlite.api')
        module.RKNNLite = FakeRKNN
        for patcher in (patch.dict(sys.modules, {'rknnlite.api': module}),
                        patch.object(detector.platform, 'system', return_value='Linux'),
                        patch.object(detector.platform, 'machine', return_value='aarch64')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_image_pipeline_saves_only_harness_and_releases_npu(self):
        app.run(self.args)
        report_path = self.root / 'output' / '测试图片_harness.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(report['harness_count'], 1)
        self.assertEqual(report['labels'], ['Harness', 'Helmet'])
        self.assertEqual([item['class_id'] for item in report['detections']], [0])
        self.assertTrue(report_path.with_suffix('.jpg').is_file())
        runtime = FakeRKNN.instances[0]
        self.assertTrue(runtime.released)
        self.assertEqual(runtime.input_shape, (1, 640, 640, 3))
        self.assertEqual(runtime.input_format, ['nhwc'])

    def test_incompatible_output_releases_npu(self):
        FakeRKNN.output = np.zeros((1, 8, 8400), dtype=np.float32)
        with self.assertRaises(ValueError):
            app.run(self.args)
        self.assertTrue(FakeRKNN.instances[0].released)

    def test_supplied_export_config_with_full_8400_output(self):
        # Exercise the supplied model's actual contract without executing its NPU graph.
        config = json.loads((app.ROOT / 'model/safety-harness-rk3588.json').read_text(encoding='utf-8'))
        config['source_model_sha256'] = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.model.with_suffix('.json').write_text(json.dumps(config), encoding='utf-8')
        FakeRKNN.output = np.pad(raw_output(), ((0, 0), (0, 0), (0, 8397)))
        app.run(self.args)
        report = json.loads((self.root / 'output/测试图片_harness.json').read_text(encoding='utf-8'))
        self.assertEqual(report['output_shapes'], [[1, 6, 8400]])
        self.assertEqual(report['output_format'], 'ultralytics_raw')
        self.assertEqual(report['harness_count'], 1)
        self.assertEqual(report['detections'][0]['class_id'], 0)
        self.assertTrue(FakeRKNN.instances[0].released)

    def test_model_hash_mismatch_rejected_before_npu_load(self):
        self.model.with_suffix('.json').write_text(json.dumps({'source_model_sha256': '0' * 64}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            app.run(self.args)
        self.assertEqual(FakeRKNN.instances, [])

    def test_init_error_releases_npu(self):
        FakeRKNN.init_code = -1
        with self.assertRaisesRegex(RuntimeError, '初始化 NPU'):
            app.run(self.args)
        self.assertTrue(FakeRKNN.instances[0].released)

    def test_tail_export_fails_with_actionable_message(self):
        (self.root / 'tail.onnx').write_bytes(b'mock')
        with self.assertRaisesRegex(ValueError, 'tail.onnx'):
            app.run(self.args)
        self.assertEqual(FakeRKNN.instances, [])

    def test_empty_model_is_rejected(self):
        self.model.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, '为空'):
            app.run(self.args)


class ImageOnlyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.image = self.root / '测试图片.png'
        self.image.write_bytes(cv2.imencode('.png', np.zeros((480, 640, 3), dtype=np.uint8))[1].tobytes())
        self.args = detect_image.parse_args(['--image', str(self.image), '--output', str(self.root / 'output')])
        self.engine = Mock(labels=['Harness', 'Helmet'], model_path=self.root / 'fake.rknn',
                           last_timing={'total_ms': 12.5}, last_output_shapes=[[1, 6, 8400]],
                           last_output_format='ultralytics_raw')
        self.engine.predict.return_value = [detector.Detection((100, 100, 200, 300), .9, 0),
                                            detector.Detection((100, 50, 200, 100), .99, 1)]
        for patcher in (patch.object(cv2, 'VideoCapture', side_effect=AssertionError('不能打开摄像头')),
                        patch.object(detector, 'Detector', return_value=self.engine)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_single_image_saves_and_prints_harness_results_without_camera(self):
        output = io.StringIO()
        with redirect_stdout(output):
            report = detect_image.run(self.args)
        self.assertEqual(report['harness_count'], 1)
        self.assertTrue(report['harness_detected'])
        self.assertEqual([item['class_id'] for item in report['detections']], [0])
        self.assertIn('0.9000', output.getvalue())
        self.assertIn('安全带检测数量：1', output.getvalue())
        self.assertTrue((self.root / 'output/测试图片_harness.jpg').is_file())
        saved = json.loads((self.root / 'output/测试图片_harness.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, report)
        self.engine.close.assert_called_once()

    def test_no_harness_is_valid_zero_result(self):
        self.engine.predict.return_value = [detector.Detection((100, 50, 200, 100), .99, 1)]
        output = io.StringIO()
        with redirect_stdout(output):
            report = detect_image.run(self.args)
        self.assertEqual(report['harness_count'], 0)
        self.assertFalse(report['harness_detected'])
        self.assertIn('未检测到', output.getvalue())

    def test_invalid_inputs_rejected_before_loading_model(self):
        for source in ('41', 'video.mp4', 'missing.jpg'):
            with self.subTest(source=source):
                self.args.image = self.root / source
                with self.assertRaises(ValueError):
                    detect_image.run(self.args)
        self.engine.predict.assert_not_called()

    def test_inference_error_releases_model(self):
        self.engine.predict.side_effect = RuntimeError('NPU失败')
        with self.assertRaisesRegex(RuntimeError, 'NPU失败'):
            detect_image.run(self.args)
        self.engine.close.assert_called_once()


class UdpTests(unittest.TestCase):
    def test_fragment_headers_reassemble_complete_image(self):
        packets = []

        class FakeSocket:
            closed = False

            def sendto(self, packet, address):
                self_address = ('127.0.0.1', 8088)
                if address != self_address:
                    raise AssertionError(address)
                packets.append(packet)
                return len(packet)

            def close(self):
                self.closed = True

        sock = FakeSocket()
        with patch.object(io_helpers.socket, 'socket', return_value=sock):
            sender = io_helpers.UdpImageSender()
            payload = b'J' * 130001
            sender.send(payload)
            sender.close()
        self.assertEqual(len(packets), 3)
        for index, packet in enumerate(packets):
            self.assertEqual(io_helpers.HEADER.unpack(packet[:16]), (1, 3, index, len(packet) - 16))
        self.assertEqual(b''.join(packet[16:] for packet in packets), payload)
        self.assertTrue(sock.closed)


if __name__ == '__main__':
    unittest.main()
