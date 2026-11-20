from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "launcher")]
import workbench_updates


class CombinedUpdateTests(unittest.TestCase):
    def test_program_is_prepared_before_publish_and_rolled_back_if_publish_fails(self):
        order = []
        with patch("tool_update.prepare_online", side_effect=lambda *args: order.append("prepare") or {"version": "2.0"}), \
             patch("workbench_updates.update_publish", side_effect=lambda *args, **kwargs: order.append("publish") or (_ for _ in ()).throw(RuntimeError("network failed"))), \
             patch("tool_update.recover_update") as recover:
            with self.assertRaisesRegex(RuntimeError, "network failed"):
                workbench_updates.update_all(ROOT, "settings.json", "1.0", release={"version": "2.0"})
        self.assertEqual(order, ["prepare", "publish"])
        recover.assert_called_once_with(ROOT)

    def test_publish_updates_even_when_launcher_is_already_latest(self):
        with patch("tool_update.prepare_online") as prepare, \
             patch("workbench_updates.update_publish", return_value={"kind": "done", "unchanged": False}) as publish:
            result = workbench_updates.update_all(ROOT, "settings.json", "1.0")
        prepare.assert_not_called()
        publish.assert_called_once()
        self.assertIsNone(result["program_record"])
        self.assertFalse(result["publish"]["unchanged"])


if __name__ == "__main__":
    unittest.main()
