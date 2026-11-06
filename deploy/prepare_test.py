"""Prepare an isolated, credential-free test deployment; no production files changed."""
import json
import os
import shutil
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
deploy = root / 'deploy'
nginx = deploy / 'test-nginx'
if nginx.exists():
    raise SystemExit('test-nginx already exists; preserve existing deployment and configuration')
shutil.copytree(root / 'nginx' / 'conf.d', nginx / 'conf.d')
for name in ('test-config', 'test-data', 'test-media', 'test-emby', 'test-openlist'):
    (deploy / name).mkdir(exist_ok=True)
shutil.copytree(root / 'config' / 'templates', deploy / 'test-config' / 'templates')
for example in (root / 'config').glob('*.example'):
    shutil.copy2(example, deploy / 'test-config' / example.name)
(nginx / 'nginx.conf').write_text('''load_module /usr/lib/nginx/modules/ngx_http_js_module.so;
events { worker_connections 1024; }
http {
  default_type application/octet-stream;
  include /etc/nginx/conf.d/*.conf;
}
''')
import re
emby_conf = nginx / 'conf.d' / 'emby.conf'
emby_conf.write_text(re.sub(r'resolver [^;]+;', 'resolver 127.0.0.11 ipv6=off valid=30s;', emby_conf.read_text()))
(nginx / 'conf.d' / 'includes' / 'https.conf').write_text('# Test environment uses isolated HTTP ports.\n')
admin = nginx / 'conf.d' / 'custome' / 'location' / 'xstrm-admin.conf'
admin.write_text(admin.read_text().replace('127.0.0.1:18095', 'admin:18095'))
constant = nginx / 'conf.d' / 'constant.js'
import re
content = re.sub(r'const embyHost = .*?;', 'const embyHost = \"http://emby:8096\";', constant.read_text())
content = re.sub(r'const mediaMountPath = .*?;', 'const mediaMountPath = [\"\"];', content)
constant.write_text(content)
mount = nginx / 'conf.d' / 'config' / 'constant-mount.js'
content = mount.read_text().replace('http://127.0.0.1:5244', 'http://openlist:5244')
mount.write_text(content)
cfg = yaml.safe_load((root / 'config' / 'strm-sync.yaml.example').read_text())
cfg.update(schema_version=1, sources=[], strm_mode='logical_path')
cfg['alist'] = {'base_url': 'http://openlist:5244', 'public_url': os.environ.get('XSTRM_PUBLIC_URL', 'http://127.0.0.1:18091'), 'token': ''}
cfg['emby'] = {'host': 'http://emby:8096', 'api_key': ''}
cfg['emby2alist']['media_mount_path'] = ['']
cfg['emby2alist']['profile_root'] = '/opt/xstrm-suite/nginx'
cfg['playback'] = {'backend': 'emby2alist', 'fallback_to_emby': True, 'check_redirect': False, 'client_self_alist_115': True}
path = deploy / 'test-config' / 'strm-sync.yaml'
path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
path.chmod(0o600)
print('Prepared isolated test configuration; create admin htpasswd before starting gateway.')
