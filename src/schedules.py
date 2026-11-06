"""Validated per-source plans. Cron accepts 5 fields or fixed seconds first."""
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from src import control


def source_key(source):
    fields = [source.get('scan_path', '').rstrip('/') or '/', source.get('output_prefix', '').rstrip('/') or '/']
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()[:24]


def sources(cfg):
    return {source_key(source): source for source in cfg.get('sources', [])}


def next_time(job, now):
    if job['trigger'] == 'interval':
        return now + job['interval_minutes'] * 60
    expression = job['cron'] if job['trigger'] == 'cron' else '{} {} * * *'.format(*reversed(job['daily_time'].split(':')))
    base = datetime.fromtimestamp(now, ZoneInfo(job['timezone']))
    try:
        return croniter(expression, base, second_at_beginning=len(expression.split()) == 6,
                        max_years_between_matches=8).get_next(datetime).timestamp()
    except (ValueError, KeyError) as exc:
        raise ValueError('Cron 无法计算下一次执行时间，请检查表达式') from exc


def validate(data, cfg, now=None, require_source=True):
    if not isinstance(data, dict):
        raise ValueError('定时任务必须是一个对象')
    job = copy.deepcopy(data)
    job['id'] = job.get('id') or uuid.uuid4().hex
    if not isinstance(job['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', job['id']):
        raise ValueError('任务 ID 格式无效')
    name = job.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('请填写不超过 100 字的任务名称')
    job['name'] = name.strip()
    if type(job.get('enabled', False)) is not bool:
        raise ValueError('任务启用状态必须是布尔值')
    job['enabled'] = job.get('enabled', False)
    if type(job.get('refresh_emby', True)) is not bool:
        raise ValueError('Emby 刷新开关必须是布尔值')
    job['refresh_emby'] = job.get('refresh_emby', True)
    if not isinstance(job.get('source_key'), str) or (require_source and job['source_key'] not in sources(cfg)):
        raise ValueError('请选择仍然存在的同步源；源目录或输出前缀改变后需要重新选择')
    job['timezone'] = job.get('timezone', 'Asia/Shanghai')
    if job['timezone'] != 'Asia/Shanghai':
        raise ValueError('当前定时任务统一使用 Asia/Shanghai（北京时间）')
    job['mode'] = job.get('mode', 'new')
    if job['mode'] not in ('new', 'all'):
        raise ValueError('扫描模式必须是最近新增或全部文件')
    for key, default, low, high in [('recent_hours', 24, 1, 720), ('interval_minutes', 360, 1, 43200),
                                   ('max_retries', 1, 0, 3), ('retry_delay_minutes', 5, 1, 120),
                                   ('timeout_minutes', 120, 1, 1440)]:
        value = job.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} 必须是 {low}–{high} 的整数')
        job[key] = value
    job['trigger'] = job.get('trigger', 'interval')
    if job['trigger'] not in ('interval', 'daily', 'cron'):
        raise ValueError('请选择按间隔、每天固定时间或 Cron')
    job['daily_time'] = job.get('daily_time', '03:00')
    if not isinstance(job['daily_time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', job['daily_time']):
        raise ValueError('每日执行时间必须是 HH:MM')
    job['cron'] = job.get('cron', '0 */6 * * *')
    if not isinstance(job['cron'], str) or len(job['cron']) > 120:
        raise ValueError('Cron 表达式无效')
    fields = job['cron'].split()
    if job['trigger'] == 'cron':
        if len(fields) not in (5, 6):
            raise ValueError('Cron 使用 5 段，或 AutoFilm 风格的 6 段（秒在首位）')
        if len(fields) == 6 and (not fields[0].isdigit() or not 0 <= int(fields[0]) <= 59):
            raise ValueError('6 段 Cron 的秒字段须是 0–59 的固定值，最快每分钟一次')
        if not re.fullmatch(r'[A-Za-z0-9*,/\-\s]+', job['cron']):
            raise ValueError('Cron 仅支持数字、星期名称、星号、逗号、范围及步长')
    next_time(job, datetime.now(timezone.utc).timestamp() if now is None else now)
    keys = ('id', 'name', 'enabled', 'refresh_emby', 'source_key', 'timezone', 'mode', 'recent_hours', 'trigger',
            'interval_minutes', 'daily_time', 'cron', 'max_retries', 'retry_delay_minutes', 'timeout_minutes')
    return {key: job[key] for key in keys}


def save(path, revision, data=None, delete_id=None):
    with control.config_lock(path):
        cfg, current = control.read(path)
        if revision != current:
            raise control.Conflict('配置已改变，请重新打开任务编辑；新任务可先点击“取消编辑 / 新建”')
        jobs = cfg.setdefault('scheduled_tasks', [])
        if delete_id:
            if not any(job.get('id') == delete_id for job in jobs):
                raise ValueError('定时任务不存在')
            cfg['scheduled_tasks'] = [job for job in jobs if job.get('id') != delete_id]
        else:
            job = validate(data, cfg)
            if len(jobs) >= 64 and not any(x.get('id') == job['id'] for x in jobs):
                raise ValueError('最多配置 64 个定时任务')
            cfg['scheduled_tasks'] = [x for x in jobs if x.get('id') != job['id']] + [job]
        control.atomic_write(path, cfg)
    return control.read(path)[1]
