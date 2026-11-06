import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src import control, schedules
from src.scheduler import Scheduler, ProcessRunner


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'config/strm-sync.yaml'
        self.path.parent.mkdir()
        self.now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc).timestamp()
        self.cfg = {'emby': {'host': 'http://emby:8096', 'api_key': 'private-emby'},
                    'alist': {'base_url': 'http://openlist:5244', 'token': 'private-alist'},
                    'output_root': '/emby-strm', 'sources': [{'scan_path': '/mnt/115/sample', 'output_prefix': '/mnt/115/sample'}]}
        self.job = schedules.validate({'id':'sample','name':'样片更新','source_key':schedules.source_key(self.cfg['sources'][0]),
                                       'enabled':True,'interval_minutes':60,'refresh_emby':False}, self.cfg, self.now)
        self.cfg['scheduled_tasks'] = [self.job]
        control.atomic_write(self.path, self.cfg)
        self.calls = []

    def engine(self, runner=None):
        def success(run):
            self.calls.append(run)
            return {'state':'succeeded','message':'扫描完成'}
        return Scheduler(self.root, self.path, clock=lambda:self.now, runner=runner or success)

    def wait(self, engine):
        if engine.worker:
            engine.worker.join(3)
            self.assertFalse(engine.worker.is_alive())

    def test_interval_daily_cron_and_fixed_seconds_have_explicit_timezone(self):
        self.assertEqual(schedules.next_time(self.job, self.now), self.now+3600)
        daily = {**self.job,'trigger':'daily','daily_time':'20:00'}
        self.assertEqual(schedules.next_time(daily,self.now), self.now+7200)
        for cron, seconds in [('0 20 * * *',7200),('5 0 20 * * *',7205)]:
            job=schedules.validate({**self.job,'trigger':'cron','cron':cron},self.cfg,self.now)
            self.assertEqual(schedules.next_time(job,self.now),self.now+seconds)
        for cron in ('*/5 * * * * *','0 0 0 0 * * *','0 0 31 2 *','not cron'):
            with self.subTest(cron=cron), self.assertRaises(ValueError):
                schedules.validate({**self.job,'trigger':'cron','cron':cron},self.cfg,self.now)

    def test_invalid_plan_does_not_overwrite_connections_and_revision_conflicts(self):
        _, revision = control.read(self.path)
        for change in ({'name':''},{'source_key':'missing'},{'interval_minutes':0},{'max_retries':4},{'timezone':'UTC'},{'refresh_emby':'true'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                schedules.save(self.path,revision,{**self.job,**change})
        schedules.save(self.path,revision,{**self.job,'name':'changed'})
        with self.assertRaises(control.Conflict):
            schedules.save(self.path,revision,self.job)
        self.assertEqual(control.read(self.path)[0]['emby']['api_key'],'private-emby')

    def test_due_job_runs_once_and_history_does_not_expose_configuration(self):
        engine=self.engine();engine.sync();self.now+=3600
        engine.tick();self.wait(engine);engine.tick();self.wait(engine)
        self.assertEqual(len(self.calls),1)
        status=engine.status();self.assertEqual(status['history'][0]['state'],'succeeded')
        self.assertNotIn('private-',json.dumps(status))
        with engine.db() as db:
            self.assertIsNone(db.execute('SELECT config_json FROM runs').fetchone()[0])

    def test_overdue_ticks_coalesce_and_interval_keeps_its_phase(self):
        engine=self.engine();engine.sync();self.now+=3*3600+17
        engine.tick(dispatch=False);engine.tick(dispatch=False)
        self.assertEqual(len(engine.status()['history']),1)
        with engine.db() as db:
            next_run=db.execute('SELECT next_run FROM plans').fetchone()[0]
        self.assertEqual(next_run,datetime(2026,11,5,14,0,tzinfo=timezone.utc).timestamp())

    def test_restart_preserves_future_schedule_skips_missed_ticks_and_marks_interruption(self):
        engine=self.engine();engine.sync()
        future=engine.status()['jobs'][0]['next_run']
        restored=self.engine();restored.sync(startup=True)
        self.assertEqual(restored.status()['jobs'][0]['next_run'],future)
        run_id=restored.submit_job('sample')
        snapshots=self.root/'data/tasks/snapshots';snapshots.mkdir(parents=True)
        (snapshots/(run_id+'.yaml')).write_text('private')
        (snapshots/(run_id+'.yaml.tmp')).write_text('private')
        with restored.db() as db:db.execute("UPDATE runs SET state='running' WHERE id=?",(run_id,))
        self.now+=24*3600
        after=self.engine();after.sync(startup=True);after.tick()
        self.assertEqual(after.status()['history'][0]['state'],'interrupted')
        self.assertEqual(self.calls,[])
        self.assertEqual(len(after.status()['history']),1)
        self.assertEqual(list(snapshots.iterdir()),[])

    def test_retry_is_bounded_and_busy_lock_does_not_consume_attempt(self):
        results=iter([{'state':'busy','message':'正在执行其他任务'}, {'state':'failed','message':'失败'}, {'state':'failed','message':'失败'}])
        engine=self.engine(lambda run:next(results));engine.submit_job('sample')
        engine.tick();self.wait(engine)
        self.assertEqual(engine.status()['history'][0]['attempt'],0)
        self.now+=5;engine.tick();self.wait(engine)
        self.assertEqual(engine.status()['history'][0]['state'],'retry_wait')
        self.now+=300;engine.tick();self.wait(engine)
        history=engine.status()['history'];self.assertEqual(len(history),1)
        self.assertEqual((history[0]['state'],history[0]['attempt']),('failed',2))

    def test_disable_source_removal_and_delete_cancel_pending_automatic_runs(self):
        engine=self.engine();engine.sync();self.now+=3600;engine.tick(dispatch=False)
        cfg,rev=control.read(self.path);schedules.save(self.path,rev,{**self.job,'enabled':False});engine.sync()
        self.assertEqual(engine.status()['history'][0]['state'],'cancelled')
        _,rev=control.read(self.path);schedules.save(self.path,rev,self.job);engine.sync();self.now+=3600;engine.tick(dispatch=False)
        cfg,_=control.read(self.path);cfg['sources']=[];control.atomic_write(self.path,cfg);engine.sync()
        self.assertTrue(engine.status()['jobs'][0]['source_missing'])
        self.assertEqual(engine.status()['queued'],0)
        _,rev=control.read(self.path);schedules.save(self.path,rev,delete_id='sample');engine.sync()
        self.assertEqual(engine.status()['jobs'],[])

    def test_manual_and_scheduled_work_are_serialized_and_duplicate_triggers_merge(self):
        entered=threading.Event();release=threading.Event();active=[]
        def run(item):
            active.append(item['id']);entered.set();release.wait(3)
            return {'state':'succeeded','message':'完成'}
        engine=self.engine(run);first=engine.submit_job('sample')
        self.assertEqual(first,engine.submit_job('sample'))
        engine.tick();self.assertTrue(entered.wait(1))
        engine.submit_manual(['bash','manual.sh'],self.cfg);self.now+=3600;engine.tick()
        self.assertEqual(len(active),1)
        release.set();self.wait(engine);engine.tick();self.wait(engine)
        self.assertEqual(len(active),2)

    def test_manual_snapshot_is_unchanged_by_later_web_configuration(self):
        engine=self.engine();run_id=engine.submit_job('sample')
        cfg,_=control.read(self.path);cfg['output_root']='/new-output';cfg['emby']['api_key']='new-key';control.atomic_write(self.path,cfg)
        engine.tick();self.wait(engine)
        saved=json.loads(self.calls[0]['config_json'])
        self.assertEqual(saved['output_root'],'/emby-strm')
        self.assertEqual(saved['emby']['api_key'],'private-emby')
        self.assertEqual(len(saved['sources']),1)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux kernel lock')
    def test_single_scheduler_owner(self):
        first=self.engine();second=self.engine();first.start()
        self.addCleanup(first.stop);self.addCleanup(second.stop)
        second.start();self.assertFalse(second.status()['running']);self.assertIn('另一实例',second.error)
        first.stop();second.start();self.assertTrue(second.status()['running'])


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('flock'),'Linux shell locks')
class RunnerIntegrationTests(unittest.TestCase):
    def test_child_keeps_writer_lock_after_parent_is_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scripts=root/'scripts';scripts.mkdir()
            shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/task_lib.sh',scripts/'task_lib.sh')
            script=scripts/'parent.sh';child_file=root/'child'
            script.write_text('source "$(dirname "$0")/task_lib.sh"\nTASK_NAME=test\nLOG_FILE=test\ntask_lock\nsleep 60 &\necho $! > "$1"\nwait\n')
            parent=subprocess.Popen(['bash',str(script),str(child_file)],start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not child_file.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(child_file.exists())
                os.kill(parent.pid,9);parent.wait()
                busy=subprocess.run(['flock','-n',str(root/'data/tasks/xstrm-write.flock'),'true'])
                self.assertNotEqual(busy.returncode,0)
            finally:
                try:os.killpg(parent.pid,9)
                except ProcessLookupError:pass
                parent.wait()
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                free=subprocess.run(['flock','-n',str(root/'data/tasks/xstrm-write.flock'),'true'])
                if free.returncode==0:break
                time.sleep(.01)
            self.assertEqual(free.returncode,0)

    def test_timeout_and_shutdown_terminate_child_processes(self):
        for cancel in (False,True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);marker=root/'started';script=root/'wait.sh'
                script.write_text(('trap "" TERM\n' if cancel else '') + 'touch "$1"\nsleep 60\n')
                runner=ProcessRunner(root)
                run={'id':'wait','command_json':json.dumps(['bash',str(script),str(marker)]),'config_json':'{}','timeout_minutes':1 if cancel else .001}
                results=[];thread=threading.Thread(target=lambda:results.append(runner(run)));thread.start()
                deadline=time.monotonic()+2
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(marker.exists())
                if cancel:runner.cancel()
                thread.join(7);self.assertFalse(thread.is_alive())
                self.assertEqual(results[0]['state'],'interrupted' if cancel else 'failed')
                self.assertEqual(list((root/'data/tasks/snapshots').glob('*.yaml')),[])

    def test_snapshot_environment_is_private_and_removed_after_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir()
            script=root/'scripts/check.sh'
            script.write_text('#!/bin/bash\nset -eu\ntest -f "$XSTRM_CONFIG_PATH"\ntest -n "$XSTRM_RUN_ID"\necho TASK_OK\necho SUMMARY=发现 2 个，新增 1 个，跳过已存在文件 1 个\n')
            runner=ProcessRunner(root)
            run={'id':'run1','command_json':json.dumps(['bash',str(script)]),'config_json':json.dumps({'emby':{'api_key':'secret'}}),'timeout_minutes':1}
            result=runner(run)
            self.assertEqual(result['state'],'succeeded')
            self.assertIn('新增 1 个',result['message'])
            self.assertEqual(list((root/'data/tasks/snapshots').glob('*.yaml')),[])

    def test_kernel_lock_releases_after_killed_process_even_with_old_lock_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scripts=root/'scripts';scripts.mkdir()
            shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/task_lib.sh',scripts/'task_lib.sh')
            (root/'data/tasks/xstrm-write.lock').mkdir(parents=True)
            script=scripts/'lock.sh';marker=root/'entered'
            script.write_text('#!/bin/bash\nsource "$(dirname "$0")/task_lib.sh"\nTASK_NAME=test\nLOG_FILE=test\ntask_lock\ntouch "$1"\nsleep "$2"\n')
            first=subprocess.Popen(['bash',str(script),str(marker),'60'],start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(marker.exists())
                busy=subprocess.run(['bash',str(script),str(marker),'0'],capture_output=True,text=True)
                self.assertEqual(busy.returncode,2);self.assertTrue(busy.stdout.startswith('TASK_RUNNING'))
            finally:
                os.killpg(first.pid,9);first.wait()
            again=subprocess.run(['bash',str(script),str(marker),'0'],capture_output=True,text=True)
            self.assertEqual(again.returncode,0)


class CliExitTests(unittest.TestCase):
    def test_unavailable_source_is_a_failed_command(self):
        from cmd import cli
        with mock.patch.object(sys,'argv',['strm_x.py','--scan-all']), mock.patch.object(cli,'load_config',return_value={}), mock.patch.object(cli,'ensure_config',return_value={}), mock.patch.object(cli,'run_all_sources',return_value={'missing_sources':1}), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:cli.main()
        self.assertEqual(error.exception.code,1)
