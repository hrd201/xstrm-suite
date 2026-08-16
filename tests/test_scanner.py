import unittest
from datetime import datetime, timezone
from unittest import mock

from src import scanner


class RecentScannerTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'scan': {
                'include_ext': ['.mkv'],
                'subtitle_exts': ['.srt'],
            },
        }
        self.now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    def walk(self, listings):
        calls = []

        def fake_request(_config, _api_path, payload):
            calls.append(payload)
            return {'data': {'content': listings[payload['path']]}}

        with mock.patch.object(scanner, 'alist_request', side_effect=fake_request), \
             mock.patch.object(scanner.time, 'sleep'):
            files, subtitles = scanner.walk_alist(
                self.config,
                '/series',
                recent_hours=24,
                now=self.now,
            )
        return files, subtitles, calls

    def test_finds_recent_season_below_old_show_directory(self):
        listings = {
            '/series': [
                {'name': 'Show', 'is_dir': True, 'modified': '2026-01-01T00:00:00Z'},
            ],
            '/series/Show': [
                {'name': 'Season 2', 'is_dir': True, 'created': '2026-08-16T08:00:00Z'},
            ],
            '/series/Show/Season 2': [
                {'name': 'Episode.mkv', 'is_dir': False, 'modified': '2020-01-01T00:00:00Z'},
                {'name': 'Episode.srt', 'is_dir': False, 'modified': '2020-01-01T00:00:00Z'},
            ],
        }

        files, subtitles, calls = self.walk(listings)

        self.assertEqual(files, ['/series/Show/Season 2/Episode.mkv'])
        self.assertEqual(subtitles, ['/series/Show/Season 2/Episode.srt'])
        self.assertTrue(all(call['refresh'] for call in calls))

    def test_skips_old_file_but_still_walks_old_directories(self):
        listings = {
            '/series': [
                {'name': 'Old Show', 'is_dir': True, 'modified': '2026-01-01T00:00:00Z'},
            ],
            '/series/Old Show': [
                {'name': 'old.mkv', 'is_dir': False, 'modified': '2026-01-01T00:00:00Z'},
                {'name': 'new.mkv', 'is_dir': False, 'modified': '2026-08-16T11:00:00Z'},
            ],
        }

        files, subtitles, calls = self.walk(listings)

        self.assertEqual(files, ['/series/Old Show/new.mkv'])
        self.assertEqual(subtitles, [])
        self.assertEqual([call['path'] for call in calls], ['/series', '/series/Old Show'])

    def test_invalid_recent_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'greater than zero'):
            scanner.walk_alist(self.config, '/series', recent_hours=0, now=self.now)


if __name__ == '__main__':
    unittest.main()
