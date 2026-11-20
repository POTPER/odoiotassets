import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
from test_config_versions import write_bundle
from config_visibility import read_policy, resolve_version, save_policy, validate_policy
from core import Engine, SyncError, atomic_json


class VisibilityTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def policy(self, **options):
        policy = {"default_user_visible": True, "rules": [{"prefix": "F", "user_visible": False}], "versions": {}}
        policy.update(options)
        atomic_json(self.target / "config/versions.json", policy)
        return policy

    def test_prefix_exact_override_alias_order_and_case_sensitive_matching(self):
        for name in ("F测试", "F公开", "标准交付", "教学", "f小写"):
            write_bundle(self.target, name)
        (self.target / "config/空目录").mkdir()
        self.policy(versions={"F公开": {"user_visible": True, "display_name": "正式版", "order": -2},
                              "标准交付": {"user_visible": False}, "教学": {"display_name": "教学版", "order": -1}})
        engine = Engine(self.target)
        result = engine.list_config_versions(user_only=True)
        self.assertEqual([item["version"] for item in result], ["F公开", "教学", "f小写"])
        self.assertEqual(result[0]["display_name"], "正式版")
        self.assertEqual(len(engine.list_config_versions()), 6)
        with self.assertRaisesRegex(SyncError, "未对用户开放"):
            engine.preview_config_version("F测试", user_only=True)
        with self.assertRaisesRegex(SyncError, "未对用户开放"):
            engine.activate_config_version("F测试", user_only=True)

    def test_hidden_current_names_are_not_exposed_to_users(self):
        raw = write_bundle(self.target, "F内部")
        for name, payload in raw.items():
            (self.target / name).write_bytes(payload)
        self.policy()
        engine = Engine(self.target)
        self.assertEqual(engine.task_config_status(user_only=True), "配置版本：实施配置")
        self.assertIn("F内部", engine.task_config_status())
        self.policy(versions={"F内部": {"user_visible": True, "display_name": "公开版"}})
        self.assertEqual(engine.task_config_status(user_only=True), "配置版本：公开版")

    def test_invalid_policy_blocks_user_view_and_leaves_engineer_access(self):
        write_bundle(self.target)
        path = self.target / "config/versions.json"
        for invalid in ({}, {"rules": [{"prefix": "", "user_visible": False}]},
                        {"default_user_visible": "false"}, {"versions": {"教学": {"order": True}}}):
            path.write_text(json.dumps(invalid), encoding="utf-8")
            if invalid == {}:
                self.assertEqual(len(Engine(self.target).list_config_versions(user_only=True)), 1)
                continue
            with self.assertRaises(SyncError):
                Engine(self.target).list_config_versions(user_only=True)
            self.assertEqual(len(Engine(self.target).list_config_versions()), 1)
        path.write_text("{broken", encoding="utf-8")
        self.assertIn("显示规则无效", Engine(self.target).task_config_status(user_only=True))

    def test_policy_changes_after_preview_and_during_apply_do_not_replace_active(self):
        write_bundle(self.target, "教学")
        engine = Engine(self.target)
        for name in ("TrainTaskInfo.json", "TrainOverviewInfo.json", "CodeSampleTuorialInfo.json"):
            (self.target / name).write_bytes(b"[]")
        old = {path.name: path.read_bytes() for path in self.target.glob("*.json")}
        self.policy()
        preview = engine.preview_config_version("教学", user_only=True)
        self.policy(default_user_visible=False)
        with self.assertRaises(SyncError):
            engine.activate_config_version("教学", expected_snapshot=preview["snapshot"], user_only=True)
        self.policy()
        from config_versions import _write_file
        def change_policy(path, raw, mode):
            _write_file(path, raw, mode)
            if path.parent.name.startswith("config-stage-"):
                self.policy(default_user_visible=False)
        with patch("config_versions._write_file", side_effect=change_policy), self.assertRaises(SyncError):
            engine.activate_config_version("教学", user_only=True)
        self.assertEqual(old, {path.name: path.read_bytes() for path in self.target.glob("*.json")})

    def test_save_conflict_and_first_prefix_rule_wins(self):
        write_bundle(self.target)
        engine = Engine(self.target)
        policy, snapshot = read_policy(engine)
        policy["rules"] = [{"prefix": "F公开", "user_visible": True}, {"prefix": "F", "user_visible": False}]
        save_policy(engine, policy, snapshot)
        self.assertTrue(resolve_version(validate_policy(policy), "F公开版本")["user_visible"])
        with self.assertRaisesRegex(SyncError, "发生变化"):
            save_policy(engine, policy, snapshot)

    def test_builtin_dot_and_uppercase_f_hide_without_policy_but_allow_overrides(self):
        for name in (".内部", "F测试", "f小写", "教学"):
            raw = write_bundle(self.target, name)
            if name == ".内部":
                for active, payload in raw.items():
                    (self.target / active).write_bytes(payload)
        engine = Engine(self.target)
        self.assertEqual({v["version"] for v in engine.list_config_versions(user_only=True)}, {"f小写", "教学"})
        self.assertEqual(len(engine.list_config_versions()), 4)
        self.assertEqual(engine.task_config_status(user_only=True), "配置版本：实施配置")
        for name in (".内部", "F测试"):
            with self.assertRaisesRegex(SyncError, "未对用户开放"):
                engine.activate_config_version(name, user_only=True)
        self.policy(rules=[{"prefix": ".", "user_visible": True}],
                    versions={"F测试": {"user_visible": True, "display_name": "开放版"}})
        self.assertEqual(len(engine.list_config_versions(user_only=True)), 4)
        self.policy(rules=[], default_user_visible=False, versions={"F测试": {"user_visible": True}})
        self.assertEqual([v["version"] for v in engine.list_config_versions(user_only=True)], ["F测试"])
