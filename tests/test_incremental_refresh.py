import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "incremental_strm_refresh", ROOT / "scripts" / "incremental_strm_refresh.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, listings):
        self.listings = listings

    def list_dir(self, path):
        return self.listings[path]

    def download_file(self, remote_path, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"subtitle:{remote_path}".encode())


class IncrementalRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = MODULE.Config(
            alist_base_url="http://127.0.0.1:5244/",
            alist_token="test",
            strm_output_dir=root / "strm",
            state_db=root / "state.sqlite3",
            watch_dirs=[],
            sources=[MODULE.SourceMapping("/mnt/series", "/series")],
            strm_url_template="{media_path}",
            max_dirs_per_run=20,
            request_interval_seconds=0,
            jitter_seconds=0,
            active_dir_ttl_days=21,
            recheck_active_after_hours=6,
            retry_after_minutes=1,
            max_retry_attempts=3,
            cold_dir_recheck_days=7,
            cold_dirs_per_run=0,
            remote_delete_policy="keep",
            remote_delete_grace_days=7,
            schedule_times=[],
            include_extensions={".mkv", ".mp4"},
            exclude_name_contains=[],
        )
        self.state = MODULE.State(self.config.state_db)

    def tearDown(self):
        self.state.conn.close()
        self.temp.cleanup()

    def test_alist_client_refreshes_only_requested_directory(self):
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"code": 200, "data": {"content": []}}).encode()
        response.__enter__.return_value = response
        client = MODULE.AlistClient("http://alist.invalid/", "test-token")

        with mock.patch.object(MODULE, "urlopen", return_value=response) as urlopen:
            client.list_dir("/mnt/series/Show")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["path"], "/mnt/series/Show")
        self.assertIs(payload["refresh"], True)

    def test_alist_client_retries_one_transient_timeout(self):
        timeout_response = mock.MagicMock()
        timeout_response.read.return_value = json.dumps({
            "code": 500,
            "message": "TLS handshake timeout",
        }).encode()
        timeout_response.__enter__.return_value = timeout_response
        success_response = mock.MagicMock()
        success_response.read.return_value = json.dumps({
            "code": 200,
            "data": {"content": [{"name": "episode.mkv"}]},
        }).encode()
        success_response.__enter__.return_value = success_response
        client = MODULE.AlistClient("http://alist.invalid/", "test-token")

        with mock.patch.object(MODULE, "urlopen", side_effect=[timeout_response, success_response]) as urlopen, mock.patch.object(
            MODULE.time, "sleep"
        ):
            items = client.list_dir("/mnt/series/Show")

        self.assertEqual(items, [{"name": "episode.mkv"}])
        self.assertEqual(urlopen.call_count, 2)

    def test_alist_client_downloads_subtitle_atomically(self):
        info_response = mock.MagicMock()
        info_response.read.return_value = json.dumps({
            "code": 200,
            "data": {"sign": "signed-value"},
        }).encode()
        info_response.__enter__.return_value = info_response
        download_response = mock.MagicMock()
        download_response.read.return_value = b"subtitle-content"
        download_response.headers = {"Content-Type": "application/octet-stream"}
        download_response.__enter__.return_value = download_response
        client = MODULE.AlistClient("http://alist.invalid/", "test-token")
        target = Path(self.temp.name) / "nested" / "episode.srt"

        with mock.patch.object(MODULE, "urlopen", side_effect=[info_response, download_response]) as urlopen:
            client.download_file("/mnt/series/Show/episode.srt", target)

        self.assertEqual(target.read_bytes(), b"subtitle-content")
        self.assertFalse(target.with_name("episode.srt.tmp").exists())
        self.assertIn("/d/mnt/series/Show/episode.srt", urlopen.call_args_list[1].args[0].full_url)

    def test_targeted_run_does_not_consume_unrelated_queue(self):
        self.state.queue_dir("/mnt/series/Other", "scheduled", priority=10)
        client = FakeClient({
            "/mnt/series/Show": [{"name": "Movie.mkv", "is_dir": False, "size": 10}],
        })

        with mock.patch.object(MODULE, "AlistClient", return_value=client), mock.patch.object(
            MODULE.time, "sleep"
        ):
            stats = MODULE.run_once(self.config, target_root="/mnt/series/Show")

        self.assertEqual(stats["dirs_scanned"], 1)
        self.assertEqual(stats["new_files"], 1)
        self.assertTrue((self.config.strm_output_dir / "series/Show/Movie.strm").exists())
        remaining = self.state.pop_dirs(10)
        self.assertEqual([row["remote_path"] for row in remaining], ["/mnt/series/Other"])

    def test_nested_new_show_generates_video_and_downloads_subtitle(self):
        self.config.max_dirs_per_run = 3
        client = FakeClient({
            "/mnt/series": [{"name": "Show-S1", "is_dir": True, "modified": "2026-08-16"}],
            "/mnt/series/Show-S1": [{"name": "Season 1", "is_dir": True, "modified": "2026-08-16"}],
            "/mnt/series/Show-S1/Season 1": [
                {"name": "S01E01.mkv", "is_dir": False, "size": 10},
                {"name": "S01E01.zh-CN.srt", "is_dir": False, "size": 5},
            ],
        })

        with mock.patch.object(MODULE, "AlistClient", return_value=client), mock.patch.object(
            MODULE.time, "sleep"
        ):
            stats = MODULE.run_once(self.config, target_root="/mnt/series")

        video = self.config.strm_output_dir / "series/Show-S1/Season 1/S01E01.strm"
        subtitle = self.config.strm_output_dir / "series/Show-S1/Season 1/S01E01.zh-CN.srt"
        self.assertTrue(video.exists())
        self.assertTrue(subtitle.exists())
        self.assertEqual(stats["dirs_scanned"], 3)
        self.assertEqual(stats["new_files"], 1)
        self.assertEqual(stats["subtitle_downloaded"], 1)

    def test_unscanned_child_is_queued_without_recursive_existing_child(self):
        old_path = "/mnt/series/Old"
        self.state.upsert_entry(old_path, "Old", True, None, "2026-01-01", None)
        self.state.mark_dir_scanned(old_path)
        client = FakeClient({
            "/mnt/series": [
                {"name": "Old", "is_dir": True, "modified": "2026-01-01"},
                {"name": "New", "is_dir": True, "modified": "2026-08-16"},
            ],
        })

        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series", recursive=True)
        queued = self.state.pop_dirs(2)

        self.assertEqual([row["remote_path"] for row in queued], ["/mnt/series/New"])

    def test_scanning_directory_preserves_parent_metadata(self):
        path = "/mnt/series/Show"
        self.state.upsert_entry(path, "Show", True, 0, "2026-08-16", "dir-sign")
        client = FakeClient({path: []})

        MODULE.refresh_one_dir(client, self.state, self.config, path)
        row = self.state.get_entry(path)

        self.assertEqual(row["modified"], "2026-08-16")
        self.assertEqual(row["sign"], "dir-sign")

    def test_manual_parent_refresh_reaches_existing_season(self):
        season = {"name": "Season 2", "is_dir": True, "modified": "2026-01-01"}
        self.state.upsert_entry("/mnt/series/Show/Season 2", "Season 2", True, None, "2026-01-01", None)
        client = FakeClient({
            "/mnt/series/Show": [season],
            "/mnt/series/Show/Season 2": [{"name": "S02E01.mkv", "is_dir": False, "size": 10}],
        })

        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show", recursive=True)
        queued = self.state.pop_dirs(1)
        self.assertEqual(queued[0]["remote_path"], "/mnt/series/Show/Season 2")
        MODULE.refresh_one_dir(client, self.state, self.config, queued[0]["remote_path"], recursive=True)

        target = self.config.strm_output_dir / "series/Show/Season 2/S02E01.strm"
        self.assertEqual(target.read_text().strip(), "/series/Show/Season 2/S02E01.mkv")

    def test_unchanged_child_is_not_requeued_by_regular_poll(self):
        self.state.upsert_entry("/mnt/series/Show/Season 2", "Season 2", True, None, "2026-01-01", None)
        self.state.mark_dir_scanned("/mnt/series/Show/Season 2")
        client = FakeClient({
            "/mnt/series/Show": [{"name": "Season 2", "is_dir": True, "modified": "2026-01-01"}],
        })
        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show", recursive=False)
        self.assertEqual(self.state.pop_dirs(10), [])

    def test_missing_strm_is_restored_unless_path_is_ignored(self):
        client = FakeClient({
            "/mnt/series/Show": [{"name": "Episode.mkv", "is_dir": False, "size": 10}],
        })
        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show")
        target = self.config.strm_output_dir / "series/Show/Episode.strm"
        target.unlink()
        stats = MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show")
        self.assertEqual(stats["restored_files"], 1)

        MODULE.ignore_path(self.config, "/mnt/series/Show/Episode.mkv", "test")
        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show")
        self.assertFalse(target.exists())

    def test_remote_missing_and_dead_letter_are_recorded(self):
        client = FakeClient({
            "/mnt/series/Show": [{"name": "Episode.mkv", "is_dir": False, "size": 10}],
        })
        MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show")
        client.listings["/mnt/series/Show"] = []
        stats = MODULE.refresh_one_dir(client, self.state, self.config, "/mnt/series/Show")
        self.assertEqual(stats["remote_missing"], 1)

        self.assertFalse(self.state.mark_dir_failed("/missing", "not found", 1, 0, 3))
        self.assertTrue(self.state.mark_dir_failed("/missing", "not found", 1, 2, 3))
        self.assertEqual(self.state.summary()["dead"], 1)

    def test_failed_directories_consume_run_budget(self):
        self.config.watch_dirs = ["/one", "/two", "/three"]
        self.config.max_dirs_per_run = 2

        class FailingClient:
            def __init__(self, *_args):
                pass

            def list_dir(self, _path):
                raise RuntimeError("unavailable")

        self.state.conn.close()
        with mock.patch.object(MODULE, "AlistClient", FailingClient):
            stats = MODULE.run_once(self.config)
        self.state = MODULE.State(self.config.state_db)
        self.assertEqual(stats["dirs_scanned"], 2)
        self.assertEqual(stats["errors"], 2)


if __name__ == "__main__":
    unittest.main()
