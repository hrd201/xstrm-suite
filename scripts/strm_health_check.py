#!/usr/bin/env python3
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
OUT_PATH = BASE_DIR / 'data' / 'strm-health-report.json'
EMBY_URL = 'http://127.0.0.1:8096/emby'
TEST_URL = 'https://127.0.0.1:8095'
USER_AGENT = 'VidHub/2.2.2'
USER_ID = 'a5fc8f5b7cf843dc8f9c3c904f937090'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_cfg():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8')) or {}


def emby_api_key(cfg):
    return (cfg.get('emby2alist', {}) or {}).get('api_key') or 'YOUR_EMBY_API_KEY'


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    cfg = load_cfg()
    api_key = emby_api_key(cfg)
    params = {
        'api_key': api_key,
        'Recursive': 'true',
        'IncludeItemTypes': 'Movie,Episode,Video',
        'Fields': 'Path,MediaSources',
        'Limit': '10000',
    }
    url = EMBY_URL + '/Items?' + urllib.parse.urlencode(params)
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
            f"{TEST_URL}/emby/videos/{item['id']}/stream.strm?AutoOpenLiveStream=false"
            f"&UserId={USER_ID}&MaxStreamingBitrate=500000000&reqformat=json&IsPlayback=true"
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
        main()
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
