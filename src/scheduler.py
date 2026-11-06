"""Durable, single-writer queue shared by scheduled and Web manual scans."""
import copy
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from urllib import request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src import control, schedules

ACTIVE = ('queued', 'running', 'retry_wait')


def stamp(value):
    return datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds') if value is not None else None


class ProcessRunner:
    def __init__(self, root):
        self.root = Path(root)
        self.process = None
        self.lock = threading.Lock()
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            process = self.process
        if process:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
                # A shell may exit while a descendant still owns stdout/locks.
                os.killpg(process.pid, signal.SIGKILL)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def __call__(self, run):
        directory = self.root / 'data/tasks/snapshots'
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / (run['id'] + '.yaml')
        control.atomic_write(snapshot, json.loads(run['config_json']))
        env = {**os.environ, 'XSTRM_CONFIG_PATH': str(snapshot), 'XSTRM_RUN_ID': run['id'], 'TZ': 'Asia/Shanghai'}
        try:
            with self.lock:
                if self.cancelled.is_set():
                    return {'state': 'interrupted', 'message': '服务正在停止，任务已中断'}
                self.process = subprocess.Popen(json.loads(run['command_json']), cwd=self.root, env=env,
                                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                start_new_session=True)
                process = self.process
            try:
                output, _ = process.communicate(timeout=run['timeout_minutes'] * 60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                return {'state': 'failed', 'message': '扫描超过执行时限，已停止，可查看日志排查'}
            if self.cancelled.is_set():
                return {'state': 'interrupted', 'message': '服务停止，任务已中断，等待下次计划'}
            if process.returncode == 2 and output.startswith('TASK_RUNNING'):
                return {'state': 'busy', 'message': '有其他写入任务正在执行，继续排队'}
            log_file = next((line.partition('=')[2] for line in output.splitlines() if line.startswith('LOG_FILE=')), None)
            # The shell status summary is local diagnostic data; do not return raw
            # upstream exception bodies or signed download URLs in task history.
            message = '扫描完成' if process.returncode == 0 else '扫描失败，请查看最近日志及网盘连接'
            counts = re.search(r'SUMMARY=发现 (\d+) 个，新增 (\d+) 个，跳过已存在文件 (\d+) 个', output)
            if process.returncode == 0 and counts:
                command = json.loads(run['command_json'])
                recent = len(command) > 2 and Path(command[1]).name == 'task_scan_recent.sh'
                scope = f'最近 {command[2]} 小时内匹配' if recent else '发现'
                message = f'扫描完成：{scope} {counts[1]} 个媒体文件，新增 {counts[2]} 个索引，已有 {counts[3]} 个'
            cfg = json.loads(run['config_json'])
            if process.returncode == 0 and cfg.get('_schedule_refresh_emby'):
                try:
                    emby = cfg.get('emby') or {}
                    req = request.Request(emby['host'].rstrip('/') + '/Library/Refresh', data=b'', headers={'X-Emby-Token': emby['api_key']})
                    with request.urlopen(req, timeout=15):
                        pass
                    message += '；已通知 Emby 刷新媒体库'
                except Exception:
                    return {'state': 'warning', 'message': '扫描完成，但通知 Emby 刷新失败，请手动扫描媒体库', 'log_file': log_file}
            return {'state': 'succeeded' if process.returncode == 0 else 'failed', 'message': message, 'log_file': log_file}
        finally:
            with self.lock:
                self.process = None
            snapshot.unlink(missing_ok=True)


class Scheduler:
    def __init__(self, root, config_path=None, clock=time.time, runner=None):
        self.root = Path(root)
        self.config_path = Path(config_path or self.root / 'config/strm-sync.yaml')
        self.db_path = self.root / 'data/scheduler.sqlite3'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.runner = runner or ProcessRunner(root)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.worker = None
        self.owner = None
        self.error = None
        self.guard = threading.RLock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, fingerprint TEXT, next_run REAL, valid INTEGER);
                CREATE TABLE IF NOT EXISTS runs(
                  id TEXT PRIMARY KEY, job_id TEXT, name TEXT, origin TEXT, state TEXT, created REAL,
                  started REAL, finished REAL, next_attempt REAL, attempt INTEGER DEFAULT 0,
                  max_retries INTEGER, retry_delay_minutes INTEGER, timeout_minutes INTEGER,
                  message TEXT, log_file TEXT, command_json TEXT, config_json TEXT);
                CREATE INDEX IF NOT EXISTS run_queue ON runs(state,next_attempt,created);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON runs(job_id) WHERE state IN ('queued','running','retry_wait');
            ''')
        self.db_path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def advance(job, previous, now):
        if job['trigger'] == 'interval' and previous is not None:
            seconds = job['interval_minutes'] * 60
            return previous + (int((now - previous) // seconds) + 1) * seconds
        return schedules.next_time(job, now)

    def jobs(self, cfg):
        result = {}
        for raw in cfg.get('scheduled_tasks', []):
            job = schedules.validate(raw, cfg, self.clock(), require_source=False)
            if job['id'] in result:
                raise ValueError('定时任务 ID 重复')
            result[job['id']] = job
        return result

    def sync(self, startup=False):
        with self.guard:
            return self._sync(startup)

    def _sync(self, startup=False):
        cfg, _ = control.read(self.config_path)
        jobs, source_map, now = self.jobs(cfg), schedules.sources(cfg), self.clock()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if startup:
                db.execute("UPDATE runs SET state='interrupted',finished=?,config_json=NULL,message='服务重启，上次执行状态未确认，等待下次计划' WHERE state='running'", (now,))
            for job in jobs.values():
                valid = job['enabled'] and job['source_key'] in source_map
                fingerprint = hashlib.sha256(json.dumps([job, source_map.get(job['source_key']), cfg.get('output_root')], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                previous = db.execute('SELECT * FROM plans WHERE id=?', (job['id'],)).fetchone()
                changed = not previous or previous['fingerprint'] != fingerprint
                if not valid:
                    next_run = None
                elif changed or previous['next_run'] is None:
                    next_run = schedules.next_time(job, now)
                elif startup and previous['next_run'] <= now:
                    next_run = self.advance(job, previous['next_run'], now)
                else:
                    next_run = previous['next_run']
                if not previous or changed or previous['next_run'] != next_run or previous['valid'] != int(valid):
                    db.execute('INSERT OR REPLACE INTO plans VALUES(?,?,?,?)', (job['id'], fingerprint, next_run, int(valid)))
                if changed or not valid:
                    db.execute("UPDATE runs SET state='cancelled',finished=?,config_json=NULL,message='计划已修改、停用或同步源已移除' WHERE job_id=? AND origin='schedule' AND state IN ('queued','retry_wait')", (now, job['id']))
            for row in db.execute('SELECT id FROM plans').fetchall():
                if row['id'] not in jobs:
                    db.execute('DELETE FROM plans WHERE id=?', (row['id'],))
                    db.execute("UPDATE runs SET state='cancelled',finished=?,config_json=NULL,message='定时任务已删除' WHERE job_id=? AND state IN ('queued','retry_wait')", (now, row['id']))
            if startup:
                for snapshot in (self.root / 'data/tasks/snapshots').glob('*.yaml*'):
                    if re.fullmatch(r'[0-9a-f]{32}\.yaml(?:\.tmp)?', snapshot.name):
                        run = db.execute('SELECT config_json FROM runs WHERE id=?', (snapshot.name.split('.')[0],)).fetchone()
                        if run and run['config_json'] is None:
                            snapshot.unlink(missing_ok=True)
        return cfg, jobs

    def enqueue(self, db, job, cfg, command, origin):
        existing = db.execute("SELECT id FROM runs WHERE job_id=? AND state IN ('queued','running','retry_wait')", (job['id'],)).fetchone()
        if existing:
            return existing['id']
        if db.execute("SELECT count(*) FROM runs WHERE state IN ('queued','running','retry_wait')").fetchone()[0] >= 80:
            raise control.Conflict('任务队列已满，请等待现有任务完成')
        run_id, now = uuid.uuid4().hex, self.clock()
        db.execute('''INSERT INTO runs(id,job_id,name,origin,state,created,next_attempt,max_retries,retry_delay_minutes,timeout_minutes,message,command_json,config_json)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (run_id, job['id'], job['name'], origin, 'queued', now, now, job['max_retries'], job['retry_delay_minutes'], job['timeout_minutes'],
                    '等待执行', json.dumps(command), json.dumps(cfg, ensure_ascii=False)))
        return run_id

    def submit_job(self, job_id):
        with self.guard:
            cfg, jobs = self.sync()
            if job_id not in jobs:
                raise ValueError('定时任务不存在')
            job = jobs[job_id]
            snapshot, command = self.prepare(job, cfg)
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                run_id = self.enqueue(db, job, snapshot, command, 'manual')
        self.wake.set()
        return run_id

    def prepare(self, job, cfg):
        source = schedules.sources(cfg).get(job['source_key'])
        if not source:
            raise ValueError('同步源已删除或修改，请重新选择同步源')
        snapshot = copy.deepcopy(cfg)
        snapshot['sources'] = [source]
        snapshot['_schedule_refresh_emby'] = job['refresh_emby']
        scripts = self.root / 'scripts'
        command = ['bash', str(scripts / 'task_scan_recent.sh'), str(job['recent_hours']), source['scan_path']] if job['mode'] == 'new' else ['bash', str(scripts / 'task_scan_path.sh'), source['scan_path']]
        return snapshot, command

    def submit_manual(self, command, cfg):
        key = hashlib.sha256(json.dumps(command).encode()).hexdigest()[:24]
        job = {'id': 'manual_' + key, 'name': '手动扫描', 'max_retries': 0, 'retry_delay_minutes': 5, 'timeout_minutes': 120}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            run_id = self.enqueue(db, job, cfg, command, 'manual')
        self.wake.set()
        return run_id

    def tick(self, dispatch=True):
        with self.guard:
            cfg, jobs = self.sync()
            now = self.clock()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for plan in db.execute('SELECT * FROM plans WHERE valid=1 AND next_run<=?', (now,)).fetchall():
                    job = jobs[plan['id']]
                    snapshot, command = self.prepare(job, cfg)
                    self.enqueue(db, job, snapshot, command, 'schedule')
                    db.execute('UPDATE plans SET next_run=? WHERE id=?', (self.advance(job, plan['next_run'], now), job['id']))
            if dispatch and not (self.worker and self.worker.is_alive()):
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    run = db.execute("SELECT * FROM runs WHERE state IN ('queued','retry_wait') AND next_attempt<=? ORDER BY created LIMIT 1", (now,)).fetchone()
                    if run:
                        db.execute("UPDATE runs SET state='running',started=?,attempt=attempt+1,message='正在扫描' WHERE id=?", (now, run['id']))
                        run = dict(db.execute('SELECT * FROM runs WHERE id=?', (run['id'],)).fetchone())
                if run:
                    self.worker = threading.Thread(target=self.execute, args=(run,), daemon=True)
                    self.worker.start()

    def execute(self, run):
        try:
            result = self.runner(run)
        except Exception as exc:
            result = {'state': 'failed', 'message': '执行器异常（' + type(exc).__name__ + '），请查看服务日志'}
        now, state = self.clock(), result['state']
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
            if not current or current['state'] != 'running':
                return
            delay = now + run['retry_delay_minutes'] * 60
            if state == 'busy':
                db.execute("UPDATE runs SET state='queued',attempt=attempt-1,next_attempt=?,message=? WHERE id=?", (now + 5, result['message'], run['id']))
            elif state == 'failed' and run['attempt'] <= run['max_retries'] and not self.stop_event.is_set():
                db.execute("UPDATE runs SET state='retry_wait',next_attempt=?,message=?,log_file=? WHERE id=?", (delay, '扫描失败，等待重试', result.get('log_file'), run['id']))
            else:
                db.execute('UPDATE runs SET state=?,finished=?,message=?,log_file=?,config_json=NULL WHERE id=?', (state, now, result['message'], result.get('log_file'), run['id']))
        self.wake.set()

    def status(self):
        cfg, revision = control.read(self.config_path)
        jobs, source_map, result = self.jobs(cfg), schedules.sources(cfg), []
        with self.db() as db:
            for job in jobs.values():
                plan = db.execute('SELECT * FROM plans WHERE id=?', (job['id'],)).fetchone()
                last = db.execute('SELECT * FROM runs WHERE job_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (job['id'],)).fetchone()
                source = source_map.get(job['source_key'])
                result.append({**job, 'source_path': source.get('scan_path') if source else None, 'source_missing': source is None,
                               'next_run': stamp(plan['next_run']) if plan else None, 'last_run': self.public_run(last) if last else None})
            history = [self.public_run(row) for row in db.execute('SELECT * FROM runs ORDER BY created DESC,rowid DESC LIMIT 20')]
            queued = db.execute("SELECT count(*) FROM runs WHERE state IN ('queued','retry_wait')").fetchone()[0]
        return {'revision': revision, 'running': bool(self.thread and self.thread.is_alive() and self.owner), 'error': self.error,
                'timezone': 'Asia/Shanghai', 'jobs': result, 'history': history, 'queued': queued,
                'sources': [{'key': key, 'path': value['scan_path'], 'output_prefix': value['output_prefix']} for key, value in source_map.items()]}

    @staticmethod
    def public_run(run):
        return {key: stamp(run[key]) if key in ('created', 'started', 'finished', 'next_attempt') else run[key]
                for key in ('id', 'job_id', 'name', 'origin', 'state', 'created', 'started', 'finished', 'next_attempt', 'attempt', 'message', 'log_file')}

    def start(self):
        import fcntl
        if self.thread and self.thread.is_alive():
            return
        owner = open(self.db_path.with_suffix('.owner'), 'a+')
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            owner.close()
            self.error = '另一实例正在调度，当前实例不重复启动'
            return
        self.owner = owner
        self.sync(startup=True)
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.error = None
            except Exception as exc:
                self.error = '调度配置或存储异常（' + type(exc).__name__ + '），请检查配置'
            self.wake.wait(1)
            self.wake.clear()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if hasattr(self.runner, 'cancel'):
            self.runner.cancel()
        if self.thread:
            self.thread.join(timeout=3)
        if self.worker:
            self.worker.join(timeout=8)
        if self.owner:
            self.owner.close()
            self.owner = None
