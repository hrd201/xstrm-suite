"""Web configuration bridge. strm-sync.yaml remains authoritative during migration."""
import copy
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib import request, error

import yaml


class Conflict(ValueError):
    pass


@contextmanager
def config_lock(path):
    lock = path.with_suffix(path.suffix + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise Conflict('配置正在保存，请稍后重新读取') from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def read(path):
    raw = path.read_bytes() if path.exists() else b''
    cfg = yaml.safe_load(raw) or {}
    if not isinstance(cfg, dict):
        raise ValueError('配置必须是 YAML 对象')
    return cfg, hashlib.sha256(raw).hexdigest()


def atomic_write(path, cfg):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def public(cfg, revision):
    alist = cfg.get('alist') or {}
    emby = cfg.get('emby') or {}
    playback = cfg.get('playback') or {}
    return {
        'revision': revision,
        'alist_url': alist.get('base_url', ''),
        'alist_public_url': alist.get('public_url', ''),
        'alist_token_set': bool(alist.get('token')),
        'alist_sign_enable': bool(alist.get('sign_enable', False)),
        'alist_sign_expire_hours': alist.get('sign_expire_time', 12),
        'emby_url': emby.get('host', ''),
        'emby_key_set': bool(emby.get('api_key')),
        'output_root': cfg.get('output_root', '/emby-strm'),
        'subtitle_sync': (cfg.get('scan') or {}).get('subtitle_sync', True),
        'fallback_to_emby': playback.get('fallback_to_emby', True),
        'check_redirect': playback.get('check_redirect', False),
        'client_self_alist_115': playback.get('client_self_alist_115', True),
        'backend': playback.get('backend', 'emby2alist'),
        'deployment': '播放配置保存后需预览并在部署环境校验应用；不会自动重启服务',
    }


def valid_url(value, field, optional=False):
    if not isinstance(value, str):
        raise ValueError(field + ' 必须是字符串')
    if optional and not value:
        return value
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError:
        raise ValueError(field + ' 地址无效') from None
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError(field + ' 必须是无内嵌密码的 HTTP(S) 地址')
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(field + ' 不允许控制字符')
    return value.rstrip('/')


def updated(cfg, data):
    if not isinstance(data, dict):
        raise ValueError('请求必须是对象')
    result = copy.deepcopy(cfg)
    result.setdefault('alist', {})
    result.setdefault('emby', {})
    result.setdefault('scan', {})
    result.setdefault('playback', {})
    for field, section, key in [('alist_url', 'alist', 'base_url'), ('alist_public_url', 'alist', 'public_url'), ('emby_url', 'emby', 'host')]:
        if field in data:
            result[section][key] = valid_url(data[field], field, optional=field == 'alist_public_url')
    for field, section, key in [('alist_token', 'alist', 'token'), ('emby_key', 'emby', 'api_key')]:
        if field in data:
            if not isinstance(data[field], str) or any(ord(c) < 32 for c in data[field]):
                raise ValueError(field + ' 格式无效')
            if data[field]:
                result[section][key] = data[field]
    for field in ('subtitle_sync', 'fallback_to_emby', 'check_redirect', 'client_self_alist_115'):
        if field in data:
            if type(data[field]) is not bool:
                raise ValueError(field + ' 必须为布尔值')
            result['scan' if field == 'subtitle_sync' else 'playback'][field] = data[field]
    if 'alist_sign_enable' in data:
        if type(data['alist_sign_enable']) is not bool:
            raise ValueError('下载签名开关必须为布尔值')
        result['alist']['sign_enable'] = data['alist_sign_enable']
    if 'alist_sign_expire_hours' in data:
        hours = data['alist_sign_expire_hours']
        if type(hours) is not int or not 1 <= hours <= 168:
            raise ValueError('签名有效期必须是 1–168 小时的整数')
        result['alist']['sign_expire_time'] = hours
    if 'output_root' in data:
        value = data['output_root']
        if not isinstance(value, str) or not value.startswith('/') or '..' in value.split('/') or any(ord(c) < 32 for c in value):
            raise ValueError('输出目录必须是没有 .. 的 Linux 绝对路径')
        result['output_root'] = value.rstrip('/') or '/'
    result['schema_version'] = 1
    backend = data.get('backend', result['playback'].get('backend', 'emby2alist'))
    if backend not in ('emby2alist', 'mediawarp'):
        raise ValueError('播放后端必须是 emby2alist 或 mediawarp')
    result['playback']['backend'] = backend
    return result


def save(path, data):
    with config_lock(path):
        cfg, revision = read(path)
        if data.get('revision') != revision:
            raise Conflict('配置已改变，请重新读取后再保存')
        result = updated(cfg, data)
        if path.exists():
            backup = path.with_suffix(path.suffix + '.previous')
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
        atomic_write(path, result)
        return public(*read(path))


def render_playback(cfg, redact=True):
    alist = cfg.get('alist') or {}
    emby = cfg.get('emby') or {}
    playback = cfg.get('playback') or {}
    if not alist.get('base_url') or not emby.get('host'):
        raise ValueError('请先填写 AList 和 Emby 地址')
    valid_url(alist['base_url'], 'AList')
    valid_url(emby['host'], 'Emby')
    if playback.get('backend', 'emby2alist') == 'mediawarp':
        return {'mediawarp.yaml': yaml.safe_dump(mediawarp_config(cfg, redact), allow_unicode=True, sort_keys=False)}
    token = '<已隐藏>' if redact else alist.get('token', '')
    key = '<已隐藏>' if redact else emby.get('api_key', '')
    j = lambda value: json.dumps(value, ensure_ascii=False)
    b = lambda name, default: j(playback.get(name, default))
    rules = '[[2, strHead["115"], alistPublicAddr]]' if playback.get('client_self_alist_115', True) else '[]'
    mount = '\n'.join([
        'import commonConfig from "./constant-common.js";',
        'const strHead = commonConfig.strHead;',
        f'const alistAddr = {j(alist["base_url"])};',
        f'const alistToken = {j(token)};',
        f'const alistPublicAddr = {j(alist.get("public_url", ""))};',
        f'const alistSignEnable = {j(bool(alist.get("sign_enable", False)))};',
        f'const alistSignExpireTime = {j(alist.get("sign_expire_time", 12))};',
        f'const clientSelfAlistRule = {rules};',
        f'const redirectCheckEnable = {b("check_redirect", False)};',
        f'const fallbackUseOriginal = {b("fallback_to_emby", True)};',
        'export default {alistAddr, alistToken, alistPublicAddr, alistSignEnable, alistSignExpireTime, clientSelfAlistRule, redirectCheckEnable, fallbackUseOriginal};',
    ])
    return {'constant-mount.js': mount, 'emby_connection': {'host': emby['host'], 'api_key': key}}


def mediawarp_config(cfg, redact=True):
    """Pinned MediaWarp v0.2.5 schema; use signed /d/ URLs for both drives."""
    alist = cfg.get('alist') or {}
    emby = cfg.get('emby') or {}
    valid_url(alist.get('base_url', ''), 'AList')
    valid_url(emby.get('host', ''), 'Emby')
    return {
        'port': 9000,
        'server': {'type': 'Emby', 'addr': emby['host'], 'auth': '<已隐藏>' if redact else emby.get('api_key', '')},
        # Upstream logs can contain signed URLs and client tokens. Use gateway logs.
        'log': {'access': {'console': False, 'file': False}, 'service': {'console': False, 'file': False}},
        'cache': {'enable': True, 'http_strm_ttl': '1m', 'alist_api_ttl': '1m', 'image_ttl': '0s', 'subtitle_ttl': '0s'},
        'web': {'enable': False},
        'client': {'enable': False},
        'http_strm': {'enable': False},
        'alist_strm': {
            'enable': True, 'proxy': False, 'raw_url': False,
            'list': [{'addr': alist['base_url'], 'token': '<已隐藏>' if redact else alist.get('token', ''),
                      'prefix_list': [(cfg.get('output_root') or '/emby-strm').rstrip('/') + '/']}],
        },
        'subtitle': {'enable': False, 'srt2ass': False},
    }


def test_connections(cfg):
    """Check saved credentials; never return response bodies or credential-bearing URLs."""
    results = {}
    for service in ('alist', 'emby'):
        try:
            section = cfg.get(service) or {}
            base = valid_url(section.get('base_url' if service == 'alist' else 'host', ''), service)
            secret = section.get('token' if service == 'alist' else 'api_key', '')
            if not secret:
                raise ValueError('尚未设置密钥')
            url = base + ('/api/me' if service == 'alist' else '/System/Info')
            headers = {'Authorization': secret} if service == 'alist' else {'X-Emby-Token': secret}
            with request.urlopen(request.Request(url, headers=headers), timeout=8) as response:
                payload = json.loads(response.read(1024 * 1024))
            if service == 'alist' and payload.get('code') != 200:
                results[service] = {'ok': False, 'message': '接口拒绝请求，请检查密钥与权限'}
            else:
                results[service] = {'ok': True, 'message': '连接与鉴权通过；尚未验证网盘或客户端播放'}
        except error.HTTPError as exc:
            results[service] = {'ok': False, 'message': 'HTTP ' + str(exc.code)}
        except ValueError:
            results[service] = {'ok': False, 'message': '地址或密钥缺失，或接口响应格式不兼容'}
        except (OSError, error.URLError):
            results[service] = {'ok': False, 'message': '连接失败或超时'}
    return results
