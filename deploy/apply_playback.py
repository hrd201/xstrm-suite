"""Run inside admin container, then nginx -t and reload on the host."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import control

cfg, _ = control.read(ROOT / 'config' / 'strm-sync.yaml')
cfg.setdefault('playback', {})['backend'] = 'emby2alist'
root = ROOT / 'nginx' / 'conf.d'
files = {
    root / 'config' / 'constant-mount.js': control.render_playback(cfg, redact=False)['constant-mount.js'],
}
constant = root / 'constant.js'
text = constant.read_text(encoding='utf-8')
for name, value in [('embyHost', cfg['emby']['host']), ('embyApiKey', cfg['emby'].get('api_key', ''))]:
    text, count = re.subn(r'const ' + name + r' = .*?;', lambda _m: 'const ' + name + ' = ' + json.dumps(value) + ';', text)
    if count != 1:
        raise SystemExit('Unexpected config shape; refusing to overwrite: ' + name)
files[constant] = text
for path, content in files.items():
    if '--rollback' in sys.argv:
        backup = path.with_suffix(path.suffix + '.previous')
        if not backup.exists():
            raise SystemExit('No rollback snapshot: ' + path.name)
        content = backup.read_text()
    else:
        backup = path.with_suffix(path.suffix + '.previous')
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(content, encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)
print('Candidate files written; nginx validation and reload are still required.')
