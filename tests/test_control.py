import tempfile
import unittest
from pathlib import Path

from src import control


class ControlTests(unittest.TestCase):
    def test_revision_and_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'config.yaml'
            control.atomic_write(p, {'alist': {'token': 'private'}, 'sources': [{'path': '/115'}], 'incremental_refresh': {'max_dirs_per_run': 7}})
            cfg, revision = control.read(p)
            result = control.save(p, {'revision': revision, 'alist_token': '', 'subtitle_sync': False})
            self.assertNotIn('private', str(result))
            saved, _ = control.read(p)
            self.assertEqual(saved['alist']['token'], 'private')
            self.assertEqual(saved['sources'], cfg['sources'])
            self.assertEqual(saved['incremental_refresh'], cfg['incremental_refresh'])
            with self.assertRaises(control.Conflict):
                control.save(p, {'revision': revision})
            self.assertTrue(p.with_suffix('.yaml.previous').exists())

    def test_invalid_values_do_not_write(self):
        for data in ({'alist_url': 'file:///etc/passwd'}, {'emby_url': 'http://user:secret@emby'}, {'subtitle_sync': 'false'}, {'output_root': '/media/../etc'}, {'emby_key': 'bad\nkey'}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                control.updated({}, data)

    def test_render_escapes_values_and_redacts_secrets(self):
        cfg = {'alist': {'base_url': 'http://alist:5244', 'token': 'secret"\\value', 'public_url': 'https://files'}, 'emby': {'host': 'http://emby:8096', 'api_key': 'key'}, 'playback': {'client_self_alist_115': False}}
        public = control.render_playback(cfg)
        self.assertNotIn('secret', str(public))
        self.assertIn('const clientSelfAlistRule = [];', public['constant-mount.js'])
        self.assertIn('secret\\"\\\\value', control.render_playback(cfg, redact=False)['constant-mount.js'])

    def test_process_lock_prevents_overlapping_saves(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'config.yaml'
            with control.config_lock(p):
                with self.assertRaises(control.Conflict):
                    with control.config_lock(p):
                        self.fail('lock acquired twice')
            self.assertFalse(p.with_suffix('.yaml.lock').exists())

    def test_backend_selection_preserves_legacy_flags(self):
        cfg = {'playback': {'backend': 'emby2alist', 'client_self_alist_115': True}}
        updated = control.updated(cfg, {'backend': 'mediawarp'})
        self.assertEqual(control.public(updated, 'r')['backend'], 'mediawarp')
        self.assertTrue(updated['playback']['client_self_alist_115'])
        self.assertEqual(control.updated(updated, {})['playback']['backend'], 'mediawarp')
        with self.assertRaises(ValueError):
            control.updated(cfg, {'backend': 'unknown'})

    def test_mediawarp_preview_hides_credentials_and_uses_strm_file_prefix(self):
        import yaml
        cfg = {'output_root': '/emby-strm', 'emby': {'host': 'http://emby:8096', 'api_key': 'emby-secret'},
               'alist': {'base_url': 'http://openlist:5244', 'token': 'alist-secret'}, 'playback': {'backend': 'mediawarp'}}
        preview = control.render_playback(cfg)
        self.assertNotIn('emby-secret', str(preview))
        self.assertNotIn('alist-secret', str(preview))
        result = yaml.safe_load(preview['mediawarp.yaml'])
        self.assertEqual(result['alist_strm']['list'][0]['prefix_list'], ['/emby-strm/'])
        self.assertFalse(result['alist_strm']['raw_url'])
        self.assertFalse(result['alist_strm']['proxy'])
        self.assertFalse(result['log']['access']['console'])
        self.assertEqual(control.mediawarp_config(cfg, redact=False)['server']['auth'], 'emby-secret')
