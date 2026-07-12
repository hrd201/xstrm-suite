import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "admin_api.py"
SPEC = importlib.util.spec_from_file_location("admin_api", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminApiTests(unittest.TestCase):
    def test_alist_items_sort_directories_first_by_creation_time(self):
        content = [
            {"name": "new-file.mkv", "is_dir": False, "created": "2026-07-12T12:00:00Z"},
            {"name": "old-dir", "is_dir": True, "created": "2026-07-10T12:00:00Z"},
            {"name": "new-dir", "is_dir": True, "created": "2026-07-11T12:00:00Z"},
            {"name": "old-file.mkv", "is_dir": False, "created": "2026-07-09T12:00:00Z"},
        ]

        items = MODULE.normalize_alist_items(content, "/media")

        self.assertEqual(
            [item["name"] for item in items],
            ["new-dir", "old-dir", "new-file.mkv", "old-file.mkv"],
        )
        self.assertEqual(items[0]["created"], "2026-07-11T12:00:00Z")

    def test_alist_items_fall_back_to_modified_time(self):
        content = [
            {"name": "older", "is_dir": True, "modified": "2026-07-10T12:00:00Z"},
            {"name": "newer", "is_dir": True, "modified": "2026-07-11T12:00:00Z"},
        ]

        items = MODULE.normalize_alist_items(content, "/media")

        self.assertEqual([item["name"] for item in items], ["newer", "older"])

    def test_save_sync_config_replaces_file_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "strm-sync.yaml"
            config_path.write_text("old: true\n", encoding="utf-8")
            with mock.patch.object(MODULE, "CONFIG_PATH", config_path):
                MODULE.save_sync_config({"strm_mode": "auto"})

            self.assertIn("strm_mode: auto", config_path.read_text(encoding="utf-8"))
            self.assertFalse(config_path.with_name("strm-sync.yaml.tmp").exists())
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)

    def test_post_permission_error_returns_json_response(self):
        handler = MODULE.Handler.__new__(MODULE.Handler)
        handler._handle_post = mock.Mock(side_effect=PermissionError("denied"))
        handler._json = mock.Mock(side_effect=lambda code, data: (code, data))

        with mock.patch.object(MODULE.traceback, "print_exc"):
            code, data = handler.do_POST()

        self.assertEqual(code, 500)
        self.assertFalse(data["ok"])
        self.assertIn("写权限", data["error"])


if __name__ == "__main__":
    unittest.main()
