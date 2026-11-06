"""Human-confirmed movie identity repair using Emby's own metadata providers.

No media is renamed, fetched or deleted. Candidate IDs are opaque, short lived,
and bound to an Emby server, item, providers and exact local STRM contents.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib import request, error
from urllib.parse import urlencode

from src import control


class IdentityError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def hints(path):
    """Conservative search suggestions, never an automatic identity decision."""
    parsed = []
    for name in (Path(path).stem, Path(path).parent.name):
        text = unicodedata.normalize('NFKC', name)
        ids = re.findall(r'[\[{]tmdb(?:id)?[=\-](\d+)[\]}]', text, re.I)
        years = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', text)
        text = re.sub(r'[\[{]tmdb(?:id)?[=\-]\d+[\]}]', ' ', text, flags=re.I)
        text = re.sub(r'\[[^\]]*\]|【[^】]*】', ' ', text)
        # Stop at release/quality markers, but preserve sequel numbers in titles.
        text = re.split(r'(?i)(?<![a-z])(?:\d{3,4}p|[48]K|REMUX|BluRay|Blu-ray|WEB[- .]?DL|HDR\d*\+?|DV|H[ .]?26[45]|HEVC|x26[45]|DTS|DDP|杜比|国英|内封|特效字幕|德版)(?![a-z])', text)[0]
        text = re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)', ' ', text)
        text = re.sub(r'^[A-Za-z]\s+(?=[\u3400-\u9fff])', '', text)
        text = re.sub(r'[._()\[\]{}]+', ' ', text).strip(' -')
        text = re.sub(r'\s+', ' ', text)
        if re.search(r'合集|系列|三部曲|\d+部', text):
            text = ''
        parsed.append({'query': text if re.search(r'[^\W\d_]', text) else '', 'years': years, 'tmdb_id': ids[0] if ids else ''})
    queries = list(dict.fromkeys(p['query'] for p in parsed if p['query']))
    years = sorted(set(y for p in parsed for y in p['years']))
    ids = sorted(set(p['tmdb_id'] for p in parsed if p['tmdb_id']))
    warnings = []
    if len(years) > 1:
        warnings.append('文件名和目录中的年份不一致，请核对后选择')
    if len(ids) > 1:
        warnings.append('文件名和目录中的 TMDB ID 不一致，请手动核对')
    if not queries:
        warnings.append('没有提取到可靠片名，请输入搜索词或 TMDB ID')
    return {'query': queries[0] if queries else '', 'alternatives': queries[1:],
            'year': int(years[0]) if len(years) == 1 else None,
            'tmdb_id': ids[0] if len(ids) == 1 else '', 'warnings': warnings}


class EmbyClient:
    def __init__(self, cfg):
        emby = cfg.get('emby') or {}
        self.base = str(emby.get('host') or '').rstrip('/')
        self.key = str(emby.get('api_key') or '')
        if not self.base or not self.key:
            raise IdentityError('请先在设置中配置 Emby 地址和 API Key')
        control.valid_url(self.base, 'Emby')
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = request.build_opener(NoRedirect())

    def call(self, path, data=None, image=False):
        req = request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                              headers={'X-Emby-Token': self.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=35) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise IdentityError('Emby 响应过大，请缩小查询范围', 502)
                if image:
                    mime = response.headers.get('Content-Type', '').split(';')[0]
                    if mime not in ('image/jpeg', 'image/png', 'image/webp'):
                        raise IdentityError('候选海报暂不可用', 502)
                    return raw, mime
                return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            raise IdentityError('Emby 认证失败，请检查 API Key' if exc.code in (401, 403) else f'Emby 请求失败（HTTP {exc.code}）', 502) from None
        except (error.URLError, TimeoutError, OSError, ValueError):
            raise IdentityError('Emby 请求超时或响应异常，请检查连接与刮削网络', 502) from None


class IdentityService:
    def __init__(self, root, config_path, client_factory=EmbyClient, clock=time.time):
        self.root, self.config_path = Path(root), Path(config_path)
        self.factory, self.clock = client_factory, clock
        self.mutex = threading.Lock()
        directory = self.root / 'data/identity'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / 'identity.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, server TEXT, item TEXT,
                    revision TEXT, fingerprint TEXT, snapshot TEXT, result TEXT, created REAL, operation TEXT);
                CREATE TABLE IF NOT EXISTS bindings (server TEXT, path TEXT, fingerprint TEXT,
                    target TEXT, result TEXT, confirmed REAL, PRIMARY KEY(server,path));
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, server TEXT, item TEXT,
                    path TEXT, fingerprint TEXT, expected TEXT, previous TEXT, state TEXT,
                    message TEXT, created REAL, updated REAL);
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(operations)')}
            for name in ('submitted', 'replace_images'):
                if name not in columns:
                    db.execute(f'ALTER TABLE operations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def context(self):
        cfg, _ = control.read(self.config_path)
        client = self.factory(cfg)
        server = str((client.call('/System/Info') or {}).get('Id') or '')
        if not server:
            raise IdentityError('无法确定 Emby 服务器身份，请检查连接', 502)
        return cfg, client, server

    def snapshot(self, item, cfg):
        path = Path(str(item.get('Path') or ''))
        root = Path(cfg.get('output_root') or '/emby-strm').resolve()
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if path.suffix.lower() != '.strm' or not resolved.is_file() or resolved.stat().st_size > 16384:
                raise ValueError()
            target = resolved.read_text(encoding='utf-8').strip()
            if not target or '\n' in target or '\r' in target:
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise IdentityError('STRM 不存在、格式异常或不在配置的输出目录中，已停止修改', 409) from None
        public = {'id': str(item.get('Id')), 'path': str(path), 'name': item.get('Name') or path.stem,
                  'year': item.get('ProductionYear'), 'providers': item.get('ProviderIds') or {},
                  'poster_tag': (item.get('ImageTags') or {}).get('Primary'),
                  'has_overview': bool(item.get('Overview')), 'has_poster': bool((item.get('ImageTags') or {}).get('Primary'))}
        fingerprint = hashlib.sha256(target.encode()).hexdigest()
        revision = hashlib.sha256(json.dumps([public['id'], public['path'], public['providers'], fingerprint], sort_keys=True).encode()).hexdigest()
        return public, fingerprint, revision, target

    def item(self, client, cfg, item_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(item_id or '')):
            raise IdentityError('影片编号无效')
        data = client.call('/Items?' + urlencode({'Ids': item_id, 'Fields': 'Path,ProviderIds,Overview', 'Limit': 1})) or {}
        items = data.get('Items') or []
        if len(items) != 1 or str(items[0].get('Id')) != str(item_id) or items[0].get('Type') != 'Movie':
            raise IdentityError('影片已移除或不是电影条目，请刷新列表', 404)
        return self.snapshot(items[0], cfg)

    def listing(self, scope='unmatched'):
        if scope not in ('unmatched', 'incomplete', 'all'):
            raise IdentityError('列表范围无效')
        cfg, client, server = self.context()
        result, offset, total, excluded = [], 0, None, 0
        with self.db() as db:
            bindings = {r['path']: dict(r) for r in db.execute('SELECT * FROM bindings WHERE server=?', (server,))}
        while total is None or offset < total:
            data = client.call('/Items?' + urlencode({'Recursive': 'true', 'IncludeItemTypes': 'Movie',
                'Fields': 'Path,ProviderIds,Overview', 'StartIndex': offset, 'Limit': 200, 'SortBy': 'SortName'})) or {}
            items = data.get('Items') or []
            total = int(data.get('TotalRecordCount', len(items)))
            if not items:
                break
            for item in items:
                if Path(str(item.get('Path') or '')).suffix.lower() != '.strm':
                    continue
                try:
                    view, fingerprint, revision, _ = self.snapshot(item, cfg)
                except IdentityError:
                    excluded += 1
                    continue
                view['unmatched'] = not any(str(view['providers'].get(k) or '').strip() for k in ('Tmdb', 'Imdb', 'Tvdb'))
                view['hints'] = hints(view['path'])
                binding = bindings.get(view['path'])
                view['binding'] = None
                if binding and binding['fingerprint'] == fingerprint:
                    saved = json.loads(binding['result'])
                    view['binding'] = {'name': saved['Name'], 'year': saved.get('ProductionYear'),
                                       'tmdb_id': saved['ProviderIds']['Tmdb']}
                view['revision'] = revision
                result.append(view)
            offset += len(items)
            if offset > 100000:
                raise IdentityError('媒体库过大，请按媒体库拆分后使用此功能')
        counts = {'total': len(result), 'unmatched': sum(x['unmatched'] for x in result),
                  'incomplete': sum(not x['has_overview'] or not x['has_poster'] for x in result), 'excluded': excluded}
        selected = [x for x in result if scope == 'all' or (x['unmatched'] if scope == 'unmatched' else not x['has_overview'] or not x['has_poster'])]
        return {'items': selected, 'counts': counts, 'scope': scope}

    def search(self, data):
        cfg, client, server = self.context()
        view, fingerprint, revision, target = self.item(client, cfg, data.get('item_id'))
        if data.get('revision') != revision:
            raise IdentityError('影片或 STRM 已改变，请刷新列表后重试', 409)
        query = str(data.get('query') or '').strip()
        tmdb = str(data.get('tmdb_id') or '').strip()
        year = str(data.get('year') or '').strip()
        if len(query) > 200 or (year and not re.fullmatch(r'(?:19|20)\d{2}', year)) or (tmdb and not re.fullmatch(r'[1-9]\d{0,10}', tmdb)):
            raise IdentityError('请填写有效的片名、年份或 TMDB ID')
        if not query and not tmdb:
            raise IdentityError('请输入片名或 TMDB ID')
        info = {'Name': '' if tmdb else query, 'MetadataLanguage': 'zh', 'MetadataCountryCode': 'CN'}
        if year and not tmdb:
            info['Year'] = int(year)
        if tmdb:
            info['ProviderIds'] = {'Tmdb': tmdb}
        candidates = client.call('/Items/RemoteSearch/Movie', {'ItemId': int(view['id']) if view['id'].isdigit() else view['id'], 'SearchInfo': info}) or []
        if not isinstance(candidates, list):
            raise IdentityError('Emby 候选响应异常', 502)
        results, seen = [], set()
        with self.db() as db:
            db.execute('DELETE FROM candidates WHERE created<? AND operation IS NULL', (self.clock()-3600,))
            for value in candidates[:30]:
                providers = value.get('ProviderIds') or {}
                ident = str(providers.get('Tmdb') or '')
                if not re.fullmatch(r'[1-9]\d{0,10}', ident) or ident in seen or (tmdb and ident != tmdb):
                    continue
                seen.add(ident)
                safe = {k: value.get(k) for k in ('Name', 'ProductionYear', 'SearchProviderName', 'ImageUrl', 'Overview')}
                safe['ProviderIds'] = {'Tmdb': ident}
                imdb = str(providers.get('Imdb') or '')
                if re.fullmatch(r'tt\d+', imdb):
                    safe['ProviderIds']['Imdb'] = imdb
                safe['Name'] = str(safe['Name'] or query)
                token = uuid.uuid4().hex
                db.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,NULL)',
                           (token, server, view['id'], revision, fingerprint, json.dumps(view, ensure_ascii=False), json.dumps(safe, ensure_ascii=False), self.clock()))
                results.append({'id': token, 'name': safe['Name'], 'year': safe.get('ProductionYear'),
                                'tmdb_id': ident, 'overview': str(safe.get('Overview') or '')[:1500],
                                'year_match': bool(tmdb) or not year or str(safe.get('ProductionYear')) == year,
                                'poster': '/api/admin/xstrm/identity/image?id='+token if safe.get('ImageUrl') else None})
        return {'candidates': results, 'message': '请选择正确影片后确认；搜索排序不代表匹配正确' if results else '未找到候选，请修改片名、去掉年份或直接填写 TMDB ID'}

    @contextmanager
    def write_lock(self):
        if not self.mutex.acquire(blocking=False):
            raise IdentityError('有识别提交正在执行，请稍后重试', 409)
        lock = None
        try:
            import fcntl
            path = self.root / 'data/tasks/xstrm-write.flock'
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = path.open('a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IdentityError('扫描任务正在写入，请等待扫描完成后确认匹配', 409) from None
            yield
        finally:
            if lock:
                lock.close()
            self.mutex.release()

    def apply(self, data):
        if data.get('confirmed') is not True:
            raise IdentityError('请先确认候选影片')
        if not isinstance(data.get('replace_images', False), bool):
            raise IdentityError('图片替换选项必须为布尔值')
        with self.write_lock():
            cfg, client, server = self.context()
            with self.db() as db:
                row = db.execute('SELECT * FROM candidates WHERE id=?', (str(data.get('candidate_id') or ''),)).fetchone()
            if not row or row['server'] != server:
                raise IdentityError('候选无效，请重新搜索', 404)
            if row['operation']:
                return {'operation_id': row['operation'], 'message': '此候选已提交，请查看处理结果'}
            if row['created'] < self.clock()-1800:
                raise IdentityError('候选已过期，请重新搜索', 409)
            with self.db() as db:
                active = db.execute("SELECT id FROM operations WHERE server=? AND item=? AND state='refreshing' AND created>?", (server, row['item'], self.clock()-180)).fetchone()
            if active:
                raise IdentityError('该影片已有识别提交正在核对，请查看处理记录', 409)
            view, fingerprint, revision, target = self.item(client, cfg, row['item'])
            if revision != row['revision'] or fingerprint != row['fingerprint']:
                raise IdentityError('条目身份或 STRM 已改变，请重新搜索确认', 409)
            candidate = json.loads(row['result'])
            operation = uuid.uuid4().hex
            now = self.clock()
            with self.db() as db:
                db.execute('INSERT INTO operations (id,server,item,path,fingerprint,expected,previous,state,message,created,updated,replace_images) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (operation, server, view['id'], view['path'], fingerprint, row['result'], row['snapshot'], 'refreshing', '匹配已确认，正在提交 Emby 并核对刮削结果', now, now, int(data.get('replace_images', False))))
                db.execute('UPDATE candidates SET operation=? WHERE id=?', (operation, row['id']))
                db.execute('INSERT OR REPLACE INTO bindings VALUES (?,?,?,?,?,?)',
                           (server, view['path'], fingerprint, target, row['result'], now))
            try:
                client.call('/Items/RemoteSearch/Apply/' + view['id'] + '?ReplaceAllImages=' + ('true' if data.get('replace_images') else 'false'), candidate)
                with self.db() as db:
                    db.execute('UPDATE operations SET submitted=1 WHERE id=?', (operation,))
            except IdentityError:
                with self.db() as db:
                    db.execute('UPDATE operations SET message=?,updated=? WHERE id=?',
                               ('提交响应异常，正在核对 Emby 实际结果；请勿重复确认', self.clock(), operation))
            return {'operation_id': operation, 'message': '确认结果已保存，正在核对 Emby 刮削状态'}

    def operation(self, operation_id):
        cfg, client, server = self.context()
        with self.db() as db:
            row = db.execute('SELECT * FROM operations WHERE id=? AND server=?', (str(operation_id), server)).fetchone()
        if not row:
            raise IdentityError('处理记录不存在或属于其他 Emby 服务器', 404)
        state, message = row['state'], row['message']
        if state in ('refreshing', 'warning'):
            try:
                view, fingerprint, _, _ = self.item(client, cfg, row['item'])
                expected_result = json.loads(row['expected'])
                expected = expected_result['ProviderIds']['Tmdb']
                previous = json.loads(row['previous'])
                matched = str(view['providers'].get('Tmdb')) == expected
                changed_identity = str(previous['providers'].get('Tmdb')) != expected
                submit_verified = bool(row['submitted']) or changed_identity
                image_verified = not row['replace_images'] or not previous.get('poster_tag') or previous.get('poster_tag') != view['poster_tag']
                if view['path'] != row['path'] or fingerprint != row['fingerprint']:
                    state, message = 'failed', 'STRM 已改变，停止核对，请刷新列表重新处理'
                elif matched and submit_verified and image_verified and view['name'] == expected_result['Name'] and view['has_overview'] and view['has_poster']:
                    state, message = 'completed', '识别修复完成：影片 ID、简介和海报已确认'
                elif self.clock()-row['created'] > 180:
                    state = 'warning'
                    if matched and not submit_verified:
                        message = '当前身份已匹配，但本次提交响应异常，无法确认刷新完成；请检查 Emby 后重新搜索'
                    elif matched and not image_verified:
                        message = '身份已绑定，已有海报标记未变化，尚不能确认图片替换；可稍后重新核对'
                    else:
                        message = '身份已绑定，但标题、简介或海报尚未补齐，可稍后在 Emby 刷新元数据' if matched else '尚未确认身份写入成功，请检查 Emby 日志后重新搜索；绑定记录已保留'
                elif matched:
                    message = '影片身份已绑定，正在等待简介和海报刷新'
            except IdentityError as exc:
                if self.clock()-row['created'] > 180:
                    state, message = 'warning', '暂时无法核对 Emby 结果，请恢复连接后重新搜索；绑定记录已保留'
                else:
                    message = str(exc)
            with self.db() as db:
                db.execute('UPDATE operations SET state=?,message=?,updated=? WHERE id=?', (state, message, self.clock(), row['id']))
        result = json.loads(row['expected'])
        return {'id': row['id'], 'item_id': row['item'], 'name': result['Name'], 'year': result.get('ProductionYear'),
                'tmdb_id': result['ProviderIds']['Tmdb'], 'state': state, 'message': message, 'created': row['created']}

    def history(self):
        _, _, server = self.context()
        with self.db() as db:
            rows = db.execute('SELECT * FROM operations WHERE server=? ORDER BY created DESC LIMIT 30', (server,)).fetchall()
        return {'history': [{'id': r['id'], 'name': json.loads(r['expected'])['Name'], 'state': r['state'],
                             'message': r['message'], 'created': r['created']} for r in rows]}

    def image(self, token):
        _, client, server = self.context()
        with self.db() as db:
            row = db.execute('SELECT * FROM candidates WHERE id=? AND server=?', (str(token), server)).fetchone()
        if not row or row['created'] < self.clock()-1800:
            raise IdentityError('候选海报已过期，请重新搜索', 404)
        result = json.loads(row['result'])
        url = result.get('ImageUrl')
        if not url or not str(url).startswith(('https://', 'http://')):
            raise IdentityError('候选海报暂不可用', 404)
        return client.call('/Items/RemoteSearch/Image?' + urlencode({'ImageUrl': url, 'ProviderName': result.get('SearchProviderName') or 'TheMovieDb'}), image=True)
