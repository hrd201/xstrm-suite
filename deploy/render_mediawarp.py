"""Generate pinned MediaWarp/edge config from the saved Web configuration."""
import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import control


def nginx_quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['config', 'gateway', 'proxy', 'revision', 'backend', 'record', 'ready'])
    parser.add_argument('--backend', choices=['emby2alist', 'mediawarp'])
    parser.add_argument('--revision')
    args = parser.parse_args()
    path = ROOT / 'config/strm-sync.yaml'
    cfg, revision = control.read(path)
    if args.action == 'config':
        if not cfg.get('emby', {}).get('api_key') or not cfg.get('alist', {}).get('token'):
            raise SystemExit('Emby / OpenList credentials are required')
        print(yaml.safe_dump(control.mediawarp_config(cfg, redact=False), allow_unicode=True, sort_keys=False), end='')
    elif args.action in ('gateway', 'proxy'):
        emby = control.valid_url(cfg['emby']['host'], 'Emby')
        alist = control.valid_url(cfg['alist']['base_url'], 'OpenList')
        public = control.valid_url(cfg['alist'].get('public_url', ''), '公网下载地址')
        template = 'mediawarp-' + ('gateway' if args.action == 'gateway' else 'proxy') + '.conf.template'
        content = (ROOT / 'deploy' / template).read_text()
        for name, value in [('EMBY_URL', emby), ('ALIST_DOWNLOAD_URL', alist + '/d/'), ('PUBLIC_DOWNLOAD_URL', public + '/d/')]:
            content = content.replace('@@' + name + '@@', nginx_quote(value))
        print(content, end='')
    elif args.action == 'revision':
        print(revision)
    elif args.action == 'backend':
        print(cfg.get('playback', {}).get('backend', 'emby2alist'))
    elif args.action == 'record':
        if not args.backend or not args.revision:
            raise SystemExit('--backend and --revision are required')
        control.save(path, {'revision': args.revision, 'backend': args.backend})
        print('Saved applied playback backend: ' + args.backend)
    elif args.action == 'ready':
        import time
        from urllib.request import urlopen
        for attempt in range(15):
            try:
                with urlopen('http://mediawarp:9000/MediaWarp/version', timeout=2) as response:
                    info = json.load(response)
                print(json.dumps(info))
                break
            except OSError:
                if attempt == 14:
                    raise SystemExit('MediaWarp did not become ready') from None
                time.sleep(1)


if __name__ == '__main__':
    main()
