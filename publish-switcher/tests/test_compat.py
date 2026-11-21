import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_switcher.common.compat import is_relative_to, remove_suffix


class CompatibilityTests(unittest.TestCase):
    def test_path_containment_keeps_boundaries(self):
        root = Path(__file__).resolve().parent
        self.assertTrue(is_relative_to(root, root))
        self.assertTrue(is_relative_to(root / "child", root))
        self.assertFalse(is_relative_to(root.with_name(root.name + "-other"), root))
        self.assertFalse(is_relative_to(root.parent, root))

    def test_suffix_removal(self):
        self.assertEqual(remove_suffix("/tmp/app (deleted)", " (deleted)"), "/tmp/app")
        self.assertEqual(remove_suffix("/tmp/app", " (deleted)"), "/tmp/app")
        self.assertEqual(remove_suffix("abc", ""), "abc")

    def test_python38_syntax_and_no_post38_path_or_string_methods(self):
        root = Path(__file__).resolve().parents[1]
        for path in (*root.glob("*.py"), *(root / "publish_switcher").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path), feature_version=8)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ("is_relative_to", "removesuffix", "removeprefix"), str(path))
