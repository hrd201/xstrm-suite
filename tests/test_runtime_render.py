import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_render', ROOT / 'scripts/render_runtime.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class RuntimeRenderTests(unittest.TestCase):
    def test_bootstrap_preserves_web_settings_and_uses_updated_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nginx = root / 'nginx'
            sync = root / 'sync.yaml'
            saved = {
                'alist': {'base_url': 'http://openlist:5244', 'token': 'new"\\token', 'public_url': 'https://files.example'},
                'emby': {'host': 'http://emby:8096', 'api_key': 'new"key'},
                'output_root': '/new-media',
                'sources': [{'scan_path': '/ali/custom', 'output_prefix': '/ali/custom'}],
                'incremental_refresh': {'max_dirs_per_run': 3},
            }
            original = yaml.safe_dump(saved).encode()
            sync.write_bytes(original)
            runtime = root / 'runtime.yaml'
            runtime.write_bytes((ROOT / 'config/runtime.yaml.example').read_bytes())
            with mock.patch.multiple(render, RUNTIME_PATH=runtime, OUT_NGINX_DIR=nginx,
                                     OUT_STRM_SYNC=sync, OUT_SITES_DIR=nginx / 'sites-enabled',
                                     OUT_COMPOSE=root / 'compose.yaml'), mock.patch('builtins.print'):
                render.main()
            self.assertEqual(sync.read_bytes(), original)
            mount = (nginx / 'conf.d/config/constant-mount.runtime.js').read_text()
            self.assertIn(json.dumps(saved['alist']['token']), mount)
            constant = (nginx / 'conf.d/constant.js.runtime').read_text()
            self.assertIn(json.dumps(saved['emby']['api_key']), constant)
