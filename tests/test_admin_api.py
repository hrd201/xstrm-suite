import importlib.util
import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "admin_api.py"
SPEC = importlib.util.spec_from_file_location("admin_api", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminApiTests(unittest.TestCase):
    def test_identity_endpoints_require_verification_and_validate_payload(self):
        from src.identity import IdentityError
        service = mock.Mock()
        def post(data, verified=True):
            handler = MODULE.Handler.__new__(MODULE.Handler)
            raw = json.dumps(data).encode()
            handler.path='/api/admin/xstrm/identity/apply'
            handler.headers={'Content-Length':str(len(raw))}
            if verified:handler.headers['X-XSTRM-Requested-With']='xstrm-admin'
            handler.rfile=io.BytesIO(raw);handler._json=lambda code,value:(code,value)
            return handler.do_POST()
        with mock.patch.object(MODULE,'IDENTITY',service):
            self.assertEqual(post({},False)[0],403)
            self.assertEqual(post([])[0],400)
            service.apply.assert_not_called()
            service.apply.return_value={'operation_id':'op'}
            self.assertEqual(post({'candidate_id':'token','confirmed':True})[0],202)
            service.apply.side_effect=IdentityError('影片已改变',409)
            self.assertEqual(post({'candidate_id':'token','confirmed':True})[0],409)
            handler=MODULE.Handler.__new__(MODULE.Handler);handler.path='/api/admin/xstrm/identity/items?scope=all'
            handler._json=lambda code,value,**kwargs:(code,value)
            service.listing.return_value={'items':[],'counts':{}}
            self.assertEqual(handler._handle_get()[0],200)
            service.listing.assert_called_once_with('all')

    def test_scheduler_api_revision_queue_and_secret_redaction(self):
        from src import schedules
        from src.scheduler import Scheduler
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'config/strm-sync.yaml';path.parent.mkdir()
            cfg={'emby':{'api_key':'hidden-api-key'},'sources':[{'scan_path':'/115/test','output_prefix':'/115/test'}]}
            MODULE.control.atomic_write(path,cfg)
            engine=Scheduler(root,path,clock=lambda:1800000000)
            def post(endpoint,data):
                handler=MODULE.Handler.__new__(MODULE.Handler);body=json.dumps(data).encode()
                handler.path='/api/admin/xstrm/scheduler/'+endpoint
                handler.headers={'Content-Length':str(len(body)),'X-XSTRM-Requested-With':'xstrm-admin'}
                handler.rfile=io.BytesIO(body);handler._json=lambda code,value:(code,value)
                return handler.do_POST()
            with mock.patch.object(MODULE,'CONFIG_PATH',path),mock.patch.object(MODULE,'SCHEDULER',engine):
                _,revision=MODULE.control.read(path)
                job={'id':'one','name':'任务','enabled':True,'source_key':schedules.source_key(cfg['sources'][0])}
                self.assertEqual(post('save',{'revision':revision,'job':job})[0],200)
                self.assertEqual(post('save',{'revision':revision,'job':job})[0],409)
                self.assertEqual(post('run',{'id':'one'})[0],202)
                self.assertEqual(post('run',{'id':'missing'})[0],400)
                self.assertNotIn('hidden-api-key',json.dumps(engine.status()))
                run_id=engine.status()['history'][0]['id']
                with engine.db() as db:db.execute("UPDATE runs SET state='running' WHERE id=?",(run_id,))
                engine.sync(startup=True)
                handler=MODULE.Handler.__new__(MODULE.Handler);handler.path='/api/admin/xstrm/status'
                handler._json=lambda code,value,**kwargs:(code,value)
                with mock.patch.object(MODULE,'run_cmd',return_value=(0,json.dumps({'run_id':run_id,'running':True}),'')):
                    _,response=handler._handle_get()
                self.assertFalse(response['status']['running'])
                self.assertEqual(response['status']['queue_state'],'interrupted')

    def test_health_scan_errors_are_not_double_encoded(self):
        handler = MODULE.Handler.__new__(MODULE.Handler)
        handler.path = '/api/admin/xstrm/strm-health'
        handler._json = lambda code, value, **kwargs: (code, value)
        with mock.patch.object(MODULE, 'run_cmd', return_value=(1, '', json.dumps({'ok': False, 'error': '请配置 Emby API Key'}))):
            code, result = handler._handle_get()
        self.assertEqual(code, 500)
        self.assertEqual(result['error'], '请配置 Emby API Key')

    def test_legacy_settings_cannot_overwrite_new_control_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sync.yaml'
            MODULE.control.atomic_write(path, {'output_root': '/old'})
            with mock.patch.object(MODULE, 'CONFIG_PATH', path):
                legacy = MODULE.load_sync_config()
                _, revision = MODULE.control.read(path)
                MODULE.control.save(path, {'revision': revision, 'output_root': '/new'})
                with self.assertRaises(MODULE.control.Conflict):
                    MODULE.save_sync_config(legacy)
            self.assertEqual(MODULE.control.read(path)[0]['output_root'], '/new')

    def test_password_update_requires_no_docker_socket(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'htpasswd'
            with mock.patch.object(MODULE, 'HTPASSWD_PATH', path), mock.patch.object(MODULE.subprocess, 'run') as run:
                run.return_value = mock.Mock(returncode=0, stdout='$apr1$test$hashed', stderr='')
                ok, _ = MODULE.update_basic_auth_password('test-password')
            self.assertTrue(ok)
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('test-password', run.call_args.args[0])
            self.assertEqual(path.read_text(), 'admin:$apr1$test$hashed\n')

    def test_control_http_revision_conflict_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sync.yaml'
            MODULE.control.atomic_write(path, {'alist': {'token': 'never-return-this'}})
            _, revision = MODULE.control.read(path)
            def post(data):
                handler = MODULE.Handler.__new__(MODULE.Handler)
                body = json.dumps(data).encode()
                handler.path = '/api/admin/xstrm/control'
                handler.headers = {'Content-Length': str(len(body)), 'X-XSTRM-Requested-With': 'xstrm-admin'}
                handler.rfile = io.BytesIO(body)
                handler._json = lambda code, value: (code, value)
                with mock.patch.object(MODULE, 'CONFIG_PATH', path):
                    return handler._handle_post()
            code, result = post({'revision': revision, 'subtitle_sync': False})
            self.assertEqual(code, 200)
            self.assertNotIn('never-return-this', json.dumps(result))
            self.assertEqual(post({'revision': revision})[0], 409)
            self.assertEqual(post([])[0], 400)

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
