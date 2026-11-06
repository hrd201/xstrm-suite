import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit


SPEC = importlib.util.spec_from_file_location('strm_health', Path(__file__).resolve().parents[1] / 'scripts/strm_health_check.py')
HEALTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEALTH)


class HealthTests(unittest.TestCase):
    def test_saved_web_key_takes_priority_and_legacy_keys_still_work(self):
        self.assertEqual(HEALTH.emby_api_key({'emby': {'api_key': 'web-key'}, 'emby2alist': {'api_key': 'old-key'}}, {'emby': {'api_key': 'runtime-key'}}), 'web-key')
        self.assertEqual(HEALTH.emby_api_key({'emby': {'api_key': 'YOUR_EMBY_API_KEY'}, 'emby2alist': {'api_key': 'old-key'}}, {}), 'old-key')
        self.assertEqual(HEALTH.emby_api_key({}, {'emby': {'api_key': 'runtime-key'}}), 'runtime-key')
        with self.assertRaisesRegex(RuntimeError, '设置'):
            HEALTH.emby_api_key({}, {})

    def test_docker_gateway_and_saved_emby_address_override_old_localhost(self):
        runtime = {'emby': {'host': 'http://127.0.0.1:8096'}, 'nginx': {'http_port': 8091}}
        with mock.patch.dict(HEALTH.os.environ, {'XSTRM_PLAYBACK_URL': 'http://gateway:8091'}, clear=True):
            self.assertEqual(HEALTH.service_urls({'emby': {'host': 'http://emby:8096/emby/'}}, runtime), ('http://emby:8096/emby', 'http://gateway:8091'))
            self.assertEqual(HEALTH.service_urls({'health': {'playback_url': 'https://example.invalid:18443/'}}, runtime)[1], 'https://example.invalid:18443')
        with mock.patch.dict(HEALTH.os.environ, {}, clear=True):
            self.assertEqual(HEALTH.service_urls({}, {'nginx': {'https_enabled': True, 'https_port': 18443}})[1], 'https://127.0.0.1:18443')
        for url in ('file:///tmp/test', 'http://user:password@host', 'https://host/?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                HEALTH.base_url(url)

    def run_scan(self, statuses):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'first.strm', root / 'second.STRM'
            first.write_text('/115/first.mkv')
            second.write_text('/ali/second.mkv')
            items = [{'Id': str(i), 'Name': 'sample-' + str(i), 'Path': str(path), 'MediaSources': [{'Id': 'mediasource_' + str(i)}]}
                     for i, path in enumerate((first, second, root / 'missing.strm'), 1)]
            requests = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    requests.append((parsed.path, parse_qs(parsed.query), self.headers.get('X-Emby-Token')))
                    if parsed.path == '/emby/Users':
                        data = [{'Id': 'user', 'Policy': {'IsAdministrator': True}}]
                    elif parsed.path == '/emby/Items':
                        start = int(parse_qs(parsed.query).get('StartIndex', ['0'])[0])
                        data = {'Items': items[start:start+2], 'TotalRecordCount': len(items)}
                    elif parsed.path in ('/emby/videos/1/stream', '/emby/videos/2/stream'):
                        code = statuses[int(parsed.path.split('/')[3]) - 1]
                        self.send_response(code)
                        if code == 302:
                            self.send_header('Location', 'https://cdn.invalid/video?sign=private-sign&api_key=private-key')
                        self.send_header('X-Xstrm-Playback-Backend', 'mediawarp')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    else:
                        self.send_error(404)
                        return
                    raw = json.dumps(data).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            cfg = {'emby': {'host': base, 'api_key': 'web-secret'}, 'health': {'playback_url': base}, 'playback': {'backend': 'mediawarp'}}
            try:
                with mock.patch.object(HEALTH, 'load_cfg', return_value=(cfg, {})), mock.patch.object(HEALTH, 'OUT_PATH', root / 'report.json'), mock.patch.object(HEALTH.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                    report = HEALTH.main()
                saved = json.loads((root / 'report.json').read_text())
                self.assertEqual(report, saved)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            return report, requests

    def test_multiple_movies_use_gateway_base_paginate_and_hide_signed_urls(self):
        report, requests = self.run_scan([302, 302])
        self.assertEqual((report['total_strm_items'], report['healthy_redirect'], report['missing_file'], report['failed_non_redirect']), (3, 2, 1, 0))
        self.assertEqual([p for p, _, _ in requests if '/videos/' in p], ['/emby/videos/1/stream', '/emby/videos/2/stream'])
        self.assertEqual([q['StartIndex'][0] for p, q, _ in requests if p == '/emby/Items'], ['0', '2'])
        for _, query, token in requests:
            self.assertNotIn('api_key', query)
            self.assertEqual(token, 'web-secret')
        self.assertEqual(report['healthy'][0]['gateway_backend'], 'mediawarp')
        self.assertEqual(report['healthy'][0]['redirect_host'], 'cdn.invalid')
        for secret in ('web-secret', 'private-sign', 'private-key'):
            self.assertNotIn(secret, json.dumps(report))

    def test_non_redirect_is_not_counted_as_healthy(self):
        report, _ = self.run_scan([200, 302])
        self.assertEqual(report['healthy_redirect'], 1)
        self.assertEqual(report['failed_non_redirect'], 1)
        self.assertEqual(report['failed'][0]['test_status'], 'non_redirect_200')

    def test_stream_responses_are_closed_without_downloading(self):
        response = mock.Mock(code=200, headers={})
        opener = mock.Mock()
        opener.open.return_value = response
        result = HEALTH.check_redirect({'id': '1', 'mediaSourceId': 'mediasource_1'}, 'http://gateway:8091', 'secret', 'user', opener)
        self.assertEqual(result['test_status'], 'non_redirect_200')
        response.read.assert_not_called()
        response.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
