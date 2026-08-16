import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "admin_api.py"
SPEC = importlib.util.spec_from_file_location("admin_api", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminApiTests(unittest.TestCase):
    def test_scan_mode_selects_recent_or_full_task(self):
        recent_task, recent_message = MODULE.scan_task_for_mode('new')
        full_task, full_message = MODULE.scan_task_for_mode('all')

        self.assertIn('task_scan_recent.sh', recent_task[1])
        self.assertEqual(recent_task[-1], '24')
        self.assertIn('24 小时', recent_message)
        self.assertIn('task_scan_incremental.sh', full_task[1])
        self.assertIn('全部文件', full_message)
        with self.assertRaises(ValueError):
            MODULE.scan_task_for_mode('invalid')

    def test_scan_path_mode_uses_recent_or_full_path_task(self):
        target = '/mnt/115/剧集'
        recent_task, _message = MODULE.scan_path_task_for_mode('new', target)
        full_task, _message = MODULE.scan_path_task_for_mode('all', target)

        self.assertIn('task_scan_recent.sh', recent_task[1])
        self.assertEqual(recent_task[-2:], ['24', target])
        self.assertIn('task_scan_path.sh', full_task[1])
        self.assertEqual(full_task[-1], target)

    def test_alist_force_refresh_is_sent_only_when_requested(self):
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"code": 200, "data": {"content": []}}).encode()
        response.__enter__.return_value = response

        with mock.patch.object(MODULE, "load_sync_config", return_value={
            "alist": {"base_url": "http://alist.invalid", "token": "test-token"},
        }), mock.patch.object(MODULE.urlrequest, "urlopen", return_value=response) as urlopen:
            ok, _ = MODULE.alist_list_dir("/media", refresh=True)

        self.assertTrue(ok)
        request_body = json.loads(urlopen.call_args.kwargs["data"])
        self.assertIs(request_body["refresh"], True)

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
