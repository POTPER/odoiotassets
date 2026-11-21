import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_switcher.demo import runner as runner
import test_iot_runner
from tools.packaging.legacy.core import Engine, SyncError


class BatchTests(unittest.TestCase):
    setUp = test_iot_runner.RunnerTests.setUp
    save = test_iot_runner.RunnerTests.save

    def task_at(self, key, folder, script_text):
        script = self.publish / 'IoT' / folder / 'demo.py'
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(script_text, encoding='utf-8')
        return dict(self.task, TrainTaskId=key, TrainTaskName=folder,
                    ScriptFloderPath='IoT/' + folder, PythonScriptPath='demo.py')

    def test_modules_execute_in_config_order_and_report_each_pid(self):
        tasks = []
        for key, previous in ((2, None), (1, 2)):
            text = ("from pathlib import Path\nimport time\nroot=Path(__file__).resolve().parents[2]\n")
            if previous is not None:
                text += "assert (root/'finished{}').exists(), 'previous module still running'\n".format(previous)
            text += ("with (root/'order').open('a') as f:f.write('{}\\n')\n".format(key) +
                     "time.sleep(.1)\n(root/'finished{}').touch()\nprint('sequential-ready')\n".format(key))
            tasks.append(self.task_at(key, '模块' + str(key), text))
        self.save(tasks)
        lines, states = [], []
        processes = []
        original_launch = runner.subprocess.Popen
        def launch(*args, **kwargs):
            for process in processes:
                self.assertIsNotNone(process.returncode, 'previous process must be reaped before next module')
                self.assertTrue(process.stdout.closed, 'previous output reader must finish before next module')
            process = original_launch(*args, **kwargs)
            processes.append(process)
            return process
        with patch('publish_switcher.demo.runner.subprocess.Popen', side_effect=launch):
            self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, output=lines.append, state=states.append,
                                             expected_tasks=tasks), 0)
        self.assertEqual((self.publish / 'order').read_text(), '2\n1\n')
        for key in ('2', '1'):
            events = [event for event in states if event['task_id'] == key]
            self.assertEqual([event['phase'] for event in events], ['queued', 'running', 'completed'])
            self.assertTrue(events[1]['pid'] > 0)
        completed_first = next(i for i,e in enumerate(states) if e['task_id'] == '2' and e['phase'] == 'completed')
        running_second = next(i for i,e in enumerate(states) if e['task_id'] == '1' and e['phase'] == 'running')
        self.assertLess(completed_first, running_second)
        log = Path(lines[0][3:]).read_text(encoding='utf-8')
        self.assertEqual(log.count('sequential-ready'), 2)
        self.assertIn('[1 模块1]', log)
        self.assertIn('[2 模块2]', log)

    def test_duplicate_script_executes_once_per_module_in_sequence(self):
        task = self.task_at(1, '共享', "from pathlib import Path\nwith Path('count').open('a') as f:f.write('once\\n')\n")
        second = dict(task, TrainTaskId=2, TrainTaskName='第二次演示')
        self.save([task, second])
        states = []
        self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, output=lambda line: None, state=states.append), 0)
        self.assertEqual((self.publish / 'IoT/共享/count').read_text(), 'once\nonce\n')
        running = [event for event in states if event['phase'] == 'running']
        self.assertEqual([event['task_id'] for event in running], ['1', '2'])
        self.assertEqual(len({event['pid'] for event in running}), 2)

    def test_all_paths_preflight_before_any_module_is_launched(self):
        valid = self.task_at(1, '有效', "from pathlib import Path\nPath('started').touch()\n")
        missing = dict(valid, TrainTaskId=2, PythonScriptPath='missing.py')
        self.save([valid, missing])
        with self.assertRaisesRegex(runner.DemoError, '不存在'):
            runner.run_many(self.publish, [1, 2], self.logs, output=lambda line: None)
        self.assertFalse((self.publish / 'IoT/有效/started').exists())
        self.assertFalse(self.logs.exists())

    def test_config_change_blocks_batch_before_start(self):
        first = self.task_at(1, '模块', "print('ok')\n")
        second = dict(first, TrainTaskId=2)
        self.save([first, second])
        with self.assertRaisesRegex(runner.DemoError, '配置.*变化'):
            runner.run_many(self.publish, [1], self.logs, expected_tasks=[first], output=lambda line: None)

    def test_failed_script_stops_batch_and_preserves_failure_status(self):
        failing = self.task_at(1, '异常', "raise RuntimeError('batch-failure')\n")
        waiting = self.task_at(2, '等待', "import time\nprint('waiting',flush=True)\ntime.sleep(30)\n")
        self.save([failing, waiting])
        states, lines = [], []
        started = time.monotonic()
        result = runner.run_many(self.publish, [1, 2], self.logs, state=states.append, output=lines.append)
        self.assertNotEqual(result, 0)
        self.assertNotEqual(result, 130)
        self.assertLess(time.monotonic() - started, 9)
        self.assertTrue(any(event['task_id'] == '1' and event['phase'] == 'failed' for event in states))
        self.assertTrue(any(event['task_id'] == '2' and event['phase'] == 'not_started' for event in states))
        self.assertFalse(any(event['task_id'] == '2' and event['phase'] == 'running' for event in states))
        self.assertIn('batch-failure', '\n'.join(lines))

    def test_script_exit_130_is_failure_for_single_and_queue(self):
        first = self.task_at(2, '自定义退出', "raise SystemExit(130)\n")
        next_task = self.task_at(1, '后续模块', "raise AssertionError('must not run')\n")
        self.save([first, next_task])
        timings = []
        code = runner.run_selected(self.publish, 2, self.logs, output=lambda line: None, progress=timings.append)
        self.assertEqual(code, 130)
        self.assertEqual(timings[-1]['phase'], 'failed')
        timings.clear()
        states = []
        code = runner.run_many(self.publish, [2, 1], self.logs, output=lambda line: None, state=states.append,
                               progress=timings.append)
        self.assertEqual(code, 130)
        self.assertEqual([item['phase'] for item in timings], ['running', 'failed', 'not_started'])
        self.assertEqual(states[-2]['exit_code'], 130)
        self.assertIn('前一模块异常', states[-1]['error'])

    def test_stop_all_keeps_lock_until_processes_exit(self):
        tasks = [self.task_at(key, '停止' + str(key), "import time\nprint('ready',flush=True)\ntime.sleep(30)\n") for key in (1, 2)]
        self.save(tasks)
        cancel = threading.Event()
        states, blocked = [], []
        def state(event):
            states.append(event)
            if event['phase'] == 'running':
                try:
                    with Engine(self.publish).lock():
                        self.fail('batch must keep the deployment lock')
                except SyncError:
                    blocked.append(event['pid'])
                if len(blocked) == 1:
                    cancel.set()
        self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, cancel=cancel, state=state, output=lambda line: None), 130)
        self.assertEqual(len(blocked), 1)
        for pid in blocked:
            if os.name == 'posix':
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
        with Engine(self.publish).lock():
            pass
        self.assertTrue(all(event['phase'] in ('stopped', 'completed', 'not_started') for event in states[-2:]))
        self.assertTrue(any(event['task_id'] == '2' and event['phase'] == 'not_started' for event in states))

    def test_start_failure_reports_failed_instead_of_not_started(self):
        states = []
        with patch('publish_switcher.demo.runner.subprocess.Popen', side_effect=OSError('test launch failure')):
            code = runner.run_selected(self.publish, 2, self.logs, state=states.append, output=lambda line: None)
        self.assertEqual(code, 1)
        self.assertEqual(states[-1]['phase'], 'failed')
        self.assertIn('test launch failure', states[-1]['error'])

    def test_cancel_before_first_module_does_not_launch_any_script(self):
        cancel = threading.Event()
        cancel.set()
        states = []
        with patch('publish_switcher.demo.runner.subprocess.Popen') as launch:
            self.assertEqual(runner.run_many(self.publish, [2], self.logs, cancel=cancel, state=states.append,
                                             output=lambda line: None), 130)
            launch.assert_not_called()
        self.assertEqual([event['phase'] for event in states], ['queued', 'not_started'])

    def test_skip_current_cleans_process_then_continues_and_rejects_stale_click(self):
        first = self.task_at(1, '长期运行', "import time\nprint('skip-ready',flush=True)\ntime.sleep(30)\n")
        second = self.task_at(2, '下一模块', "print('next-ready')\n")
        self.save([first, second])
        control = runner.DemoQueueControl()
        states, progress, processes, requests = [], [], [], []
        original = runner.subprocess.Popen
        def launch(*args, **kwargs):
            for process in processes:
                self.assertIsNotNone(process.returncode)
                self.assertTrue(process.stdout.closed)
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        def log(event):
            if 'skip-ready' in event['line']:
                requests.append(control.request_skip('1'))
                requests.append(control.request_skip('1'))
        def state(event):
            states.append(event)
            if event['task_id'] == '2' and event['phase'] == 'running':
                self.assertFalse(control.request_skip('1'), 'a late click must not skip the next module')
        with patch('publish_switcher.demo.runner.subprocess.Popen', side_effect=launch):
            result = runner.run_many(self.publish, [1, 2], self.logs, control=control, progress=progress.append,
                                     state=state, log_event=log, output=lambda line: None)
        self.assertEqual(result, 0)
        self.assertEqual(requests, [True, False])
        self.assertEqual([(p['task_id'], p['phase']) for p in progress],
                         [('1', 'running'), ('1', 'skipped'), ('2', 'running'), ('2', 'completed')])
        self.assertEqual([(p['index'], p['total']) for p in progress], [(1, 2), (1, 2), (2, 2), (2, 2)])
        self.assertTrue(all(p['elapsed'] >= 0 for p in progress))
        self.assertTrue(any(e['task_id'] == '1' and e['phase'] == 'skipped' for e in states))
        self.assertFalse(control.can_skip('2'))
        self.assertFalse(control.request_skip('2'))

    def test_stop_all_wins_over_pending_skip(self):
        tasks = [self.task_at(key, '模块' + str(key), "import time\ntime.sleep(30)\n") for key in (1, 2)]
        self.save(tasks)
        control, cancel = runner.DemoQueueControl(), threading.Event()
        states, progress = [], []
        def state(event):
            states.append(event)
            if event['phase'] == 'running':
                self.assertTrue(control.request_skip('1'))
                cancel.set()
        self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, control=control, cancel=cancel,
                                         state=state, progress=progress.append, output=lambda line: None), 130)
        self.assertFalse(any(e['task_id'] == '2' and e['phase'] == 'running' for e in states))
        self.assertEqual([p['phase'] for p in progress], ['running', 'stopped', 'not_started'])

    def test_skip_composite_stops_all_its_scripts_before_next_module(self):
        task = self.task_at(1, '组合', "import time\ntime.sleep(30)\n")
        extra = self.publish / 'IoT/组合/extra.py'
        extra.write_text("import time\ntime.sleep(30)\n", encoding='utf-8')
        task['PythonScriptPath'] = 'IoT/组合/demo.py|IoT/组合/extra.py'
        following = self.task_at(2, '后续', "print('ok')\n")
        self.save([task, following])
        control, states = runner.DemoQueueControl(), []
        def state(event):
            states.append(event)
            active = [e for e in states if e['task_id'] == '1' and e['phase'] == 'running']
            if event['phase'] == 'running' and len(active) == 2 and event['task_id'] == '1':
                control.request_skip('1')
            if event['task_id'] == '2' and event['phase'] == 'running':
                self.assertEqual(len([e for e in states if e['task_id'] == '1' and e['phase'] == 'skipped']), 2)
                if os.name == 'posix':
                    for previous in active:
                        with self.assertRaises(ProcessLookupError):
                            os.kill(previous['pid'], 0)
        self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, control=control, state=state,
                                         output=lambda line: None), 0)

    def test_skip_during_startup_does_not_spawn_and_last_skip_is_not_failure(self):
        control, states = runner.DemoQueueControl(), []
        def progress(event):
            if event['phase'] == 'running':
                self.assertTrue(control.request_skip(event['task_id']))
        with patch('publish_switcher.demo.runner.subprocess.Popen') as launch:
            self.assertEqual(runner.run_many(self.publish, [2], self.logs, control=control, progress=progress,
                                             state=states.append, output=lambda line: None), 0)
            launch.assert_not_called()
        self.assertEqual([e['phase'] for e in states], ['queued', 'skipped'])

    def test_log_events_route_by_metadata_and_expose_complete_module_files(self):
        tasks = [self.task_at(key, '日志' + str(key), "print('[other-module] unique-output-{}')\n".format(key)) for key in (1, 2)]
        self.save(tasks)
        events = []
        self.assertEqual(runner.run_many(self.publish, [1, 2], self.logs, log_event=events.append,
                                         output=lambda line: None), 0)
        self.assertIsNone(events[0]['task_id'])
        self.assertTrue(Path(events[0]['log_path']).is_file())
        for key in ('1', '2'):
            matching = [e for e in events if e['task_id'] == key]
            self.assertTrue(any('unique-output-' + key in e['line'] for e in matching))
            path = next(Path(e['module_log_path']) for e in matching if e.get('module_log_path'))
            self.assertIn('unique-output-' + key, path.read_text(encoding='utf-8'))
            self.assertNotIn('unique-output-' + ('2' if key == '1' else '1'), path.read_text(encoding='utf-8'))

    def test_single_module_has_progress_and_structured_log_path(self):
        progress, logs = [], []
        self.assertEqual(runner.run_selected(self.publish, 2, self.logs, progress=progress.append,
                                             log_event=logs.append, output=lambda line: None), 0)
        self.assertEqual([p['phase'] for p in progress], ['running', 'completed'])
        self.assertTrue(all(p['index'] == p['total'] == 1 for p in progress))
        self.assertTrue(all(e['task_id'] == '2' for e in logs))
        self.assertTrue(Path(logs[0]['log_path']).is_file())
