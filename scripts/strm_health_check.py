#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
RUNTIME_PATH = BASE_DIR / 'config' / 'runtime.yaml'
OUT_PATH = BASE_DIR / 'data' / 'strm-health-report.json'
USER_AGENT = 'VidHub/2.2.2'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_cfg():
    sync = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8')) or {}
    runtime = yaml.safe_load(RUNTIME_PATH.read_text(encoding='utf-8')) or {} if RUNTIME_PATH.exists() else {}
    return sync, runtime


def emby_api_key(sync_cfg, runtime_cfg):
    for section in (sync_cfg.get('emby'), sync_cfg.get('emby2alist'), runtime_cfg.get('emby')):
        key = (section or {}).get('api_key')
        if isinstance(key, str) and key.strip() and key.strip() != 'YOUR_EMBY_API_KEY':
            return key.strip()
    raise RuntimeError('请在“设置 → 连接与播放配置”中配置 Emby API Key 并保存')


def base_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('健康检查服务地址必须是无内嵌密码、查询参数的 HTTP(S) 地址')
    return value.rstrip('/')


def service_urls(sync_cfg, runtime_cfg):
    emby = base_url((sync_cfg.get('emby') or {}).get('host') or (runtime_cfg.get('emby') or {}).get('host') or 'http://127.0.0.1:8096')
    if not emby.lower().endswith('/emby'):
        emby += '/emby'
    proxy = (sync_cfg.get('health') or {}).get('playback_url') or os.environ.get('XSTRM_PLAYBACK_URL')
    if proxy:
        return emby, base_url(proxy)
    nginx = runtime_cfg.get('nginx', {}) or {}
    if nginx.get('https_enabled'):
        proxy = f"https://127.0.0.1:{int(nginx.get('https_port', 8095))}"
    else:
        proxy = f"http://127.0.0.1:{int(nginx.get('http_port', 8091))}"
    return emby, proxy


def fetch_json(url: str, api_key: str):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'X-Emby-Token': api_key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def library_items(emby_url, api_key, user_id):
    items = []
    while True:
        params = {'Recursive': 'true', 'IncludeItemTypes': 'Movie,Episode,Video', 'Fields': 'Path,MediaSources',
                  'UserId': user_id, 'StartIndex': len(items), 'Limit': 500}
        data = fetch_json(emby_url + '/Items?' + urllib.parse.urlencode(params), api_key)
        batch = data.get('Items') or []
        if not batch:
            break
        if items and [x.get('Id') for x in batch] == [x.get('Id') for x in items[-len(batch):]]:
            raise RuntimeError('Emby 媒体列表分页未前进，健康扫描已停止')
        items.extend(batch)
        total = data.get('TotalRecordCount')
        if (total is not None and len(items) >= total) or (total is None and len(batch) < params['Limit']):
            break
    return items


def check_redirect(item, gateway_url, api_key, user_id, opener):
    params = {'AutoOpenLiveStream': 'false', 'UserId': user_id, 'MaxStreamingBitrate': 500000000,
              'reqformat': 'json', 'IsPlayback': 'true', 'MediaSourceId': item['mediaSourceId'], 'Static': 'true'}
    url = gateway_url + '/emby/videos/' + urllib.parse.quote(item['id'], safe='') + '/stream?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'X-Emby-Token': api_key})
    try:
        resp = opener.open(req, timeout=20)
    except urllib.error.HTTPError as ex:
        resp = ex
    except Exception as ex:
        return {'test_status': 'error', 'error': type(ex).__name__}
    try:
        code = resp.code
        result = {'http_status': code, 'test_status': f'non_redirect_{code}'}
        backend = resp.headers.get('X-Xstrm-Playback-Backend')
        if backend:
            result['gateway_backend'] = backend
        location = resp.headers.get('Location')
        if code in (301, 302, 307, 308) and location:
            destination = urllib.parse.urlsplit(urllib.parse.urljoin(url, location))
            if destination.scheme in ('http', 'https') and destination.hostname and not destination.username and not destination.password:
                result.update(test_status=str(code), redirect_scheme=destination.scheme,
                              redirect_host=destination.hostname, redirect_path=destination.path)
            else:
                result['test_status'] = 'invalid_redirect'
        return result
    finally:
        # Never read a video response or follow the redirect in this check.
        resp.close()


def main(limit: int = 0):
    sync_cfg, runtime_cfg = load_cfg()
    api_key = emby_api_key(sync_cfg, runtime_cfg)
    emby_url, gateway_url = service_urls(sync_cfg, runtime_cfg)
    users = fetch_json(emby_url + '/Users', api_key)
    admin = next((user for user in users if (user.get('Policy') or {}).get('IsAdministrator')), None)
    user = admin or (users[0] if users else None)
    if not user or not user.get('Id'):
        raise RuntimeError('No Emby user is available for playback health checks')
    user_id = user['Id']
    items = library_items(emby_url, api_key, user_id)

    strm_items = []
    for it in items:
        path = it.get('Path') or ''
        media_sources = it.get('MediaSources') or []
        first = media_sources[0] if media_sources else {}
        container = first.get('Container') or ''
        media_source_id = first.get('Id') or ''
        if path.lower().endswith('.strm') or container.lower() == 'strm':
            strm_items.append({
                'id': str(it.get('Id')),
                'name': it.get('Name'),
                'path': path,
                'container': container,
                'mediaSourceId': media_source_id or str(it['Id']),
                'file_exists': bool(path and os.path.exists(path)),
            })
    available_strm_items = len(strm_items)
    if limit > 0:
        strm_items = strm_items[:limit]

    opener = urllib.request.build_opener(NoRedirect())

    healthy, missing, failed = [], [], []
    for item in strm_items:
        if not item['file_exists']:
            item['test_status'] = 'missing_file'
            missing.append(item)
            continue

        item.update(check_redirect(item, gateway_url, api_key, user_id, opener))
        if item['test_status'] in ('301', '302', '307', '308'):
            healthy.append(item)
        else:
            failed.append(item)
        time.sleep(0.2)

    report = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'check_scope': 'local_strm_and_redirect',
        'gateway_url': gateway_url,
        'configured_backend': (sync_cfg.get('playback') or {}).get('backend', 'emby2alist'),
        'available_strm_items': available_strm_items,
        'total_strm_items': len(strm_items),
        'healthy_redirect': len(healthy),
        'missing_file': len(missing),
        'failed_non_redirect': len(failed),
        'healthy': healthy,
        'missing': missing,
        'failed': failed,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT_PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(OUT_PATH)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Check Emby STRM files and proxy redirects.')
        parser.add_argument('--limit', type=int, default=0, help='Check only the first N STRM items; 0 checks all.')
        main(max(0, parser.parse_args().limit))
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError):
            message = f'Emby 接口返回 HTTP {e.code}，请检查地址、API Key 与权限'
        elif isinstance(e, urllib.error.URLError):
            message = '无法连接 Emby，请检查服务地址和容器网络'
        elif isinstance(e, (RuntimeError, ValueError)) and not isinstance(e, yaml.YAMLError):
            message = str(e)
        else:
            message = f'健康检查失败（{type(e).__name__}），请检查配置及文件权限'
        print(json.dumps({'ok': False, 'error': message}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
