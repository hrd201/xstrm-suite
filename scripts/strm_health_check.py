#!/usr/bin/env python3
import argparse
import json
import os
import ssl
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
    key = (sync_cfg.get('emby2alist', {}) or {}).get('api_key') or (runtime_cfg.get('emby', {}) or {}).get('api_key')
    if not key or key == 'YOUR_EMBY_API_KEY':
        raise RuntimeError('Emby API key is not configured')
    return key


def service_urls(runtime_cfg):
    emby = (runtime_cfg.get('emby', {}) or {}).get('host', 'http://127.0.0.1:8096').rstrip('/') + '/emby'
    nginx = runtime_cfg.get('nginx', {}) or {}
    if nginx.get('https_enabled'):
        proxy = f"https://127.0.0.1:{int(nginx.get('https_port', 8095))}"
    else:
        proxy = f"http://127.0.0.1:{int(nginx.get('http_port', 8091))}"
    return emby, proxy


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main(limit: int = 0):
    sync_cfg, runtime_cfg = load_cfg()
    api_key = emby_api_key(sync_cfg, runtime_cfg)
    emby_url, test_url = service_urls(runtime_cfg)
    users = fetch_json(emby_url + '/Users?' + urllib.parse.urlencode({'api_key': api_key}))
    admin = next((user for user in users if (user.get('Policy') or {}).get('IsAdministrator')), None)
    user = admin or (users[0] if users else None)
    if not user or not user.get('Id'):
        raise RuntimeError('No Emby user is available for playback health checks')
    user_id = user['Id']
    params = {
        'api_key': api_key,
        'Recursive': 'true',
        'IncludeItemTypes': 'Movie,Episode,Video',
        'Fields': 'Path,MediaSources',
        'Limit': '10000',
    }
    params['UserId'] = user_id
    url = emby_url + '/Items?' + urllib.parse.urlencode(params)
    data = fetch_json(url)
    items = data.get('Items', [])

    strm_items = []
    for it in items:
        path = it.get('Path') or ''
        media_sources = it.get('MediaSources') or []
        first = media_sources[0] if media_sources else {}
        container = first.get('Container') or ''
        media_source_id = first.get('Id') or ''
        if path.endswith('.strm') or container == 'strm' or '/emby-strm/' in path:
            strm_items.append({
                'id': str(it.get('Id')),
                'name': it.get('Name'),
                'path': path,
                'container': container,
                'mediaSourceId': media_source_id,
                'file_exists': bool(path and os.path.exists(path)),
            })
    available_strm_items = len(strm_items)
    if limit > 0:
        strm_items = strm_items[:limit]

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        NoRedirect(),
    )

    healthy, missing, failed = [], [], []
    for item in strm_items:
        if not item['file_exists']:
            item['test_status'] = 'missing_file'
            missing.append(item)
            continue

        test_url = (
            f"{test_url}/emby/videos/{item['id']}/stream.strm?AutoOpenLiveStream=false"
            f"&UserId={user_id}&MaxStreamingBitrate=500000000&reqformat=json&IsPlayback=true"
            f"&api_key={api_key}&MediaSourceId={urllib.parse.quote(item['mediaSourceId'])}&Static=true"
        )
        req = urllib.request.Request(test_url, headers={'User-Agent': USER_AGENT}, method='GET')
        try:
            resp = opener.open(req, timeout=20)
            code = getattr(resp, 'status', resp.getcode())
            item['http_status'] = code
            item['test_status'] = f'non_redirect_{code}'
            failed.append(item)
        except urllib.error.HTTPError as ex:
            item['http_status'] = ex.code
            item['location'] = ex.headers.get('Location')
            if ex.code in (301, 302, 307, 308) and item['location']:
                item['test_status'] = str(ex.code)
                healthy.append(item)
            else:
                item['test_status'] = f'http_{ex.code}'
                failed.append(item)
        except Exception as ex:
            item['test_status'] = 'error'
            item['error'] = str(ex)
            failed.append(item)
        time.sleep(0.2)

    report = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
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
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Check Emby STRM files and proxy redirects.')
        parser.add_argument('--limit', type=int, default=0, help='Check only the first N STRM items; 0 checks all.')
        main(max(0, parser.parse_args().limit))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
