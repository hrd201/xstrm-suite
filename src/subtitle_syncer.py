"""字幕文件同步模块 - 从 AList 下载字幕到服务器本地对应目录。"""
import time
import random
from pathlib import Path
from typing import Dict, List
from urllib import request, error
from urllib.parse import quote

from .alist_client import alist_request
from .generator import map_scan_to_media


def get_subtitle_exts(config: dict) -> set:
    """从配置中获取字幕扩展名集合，回退到内置默认值。"""
    from .config import SUBTITLE_EXTS
    raw = ((config.get('scan') or {}).get('subtitle_exts') or [])
    exts = set()
    for ext in raw:
        if not ext:
            continue
        ext = str(ext).strip().lower()
        if not ext:
            continue
        if not ext.startswith('.'):
            ext = f'.{ext}'
        exts.add(ext)
    return exts or set(SUBTITLE_EXTS)


def is_subtitle_sync_enabled(config: dict) -> bool:
    """判断字幕同步功能是否启用（默认 True）。"""
    scan_cfg = config.get('scan') or {}
    return bool(scan_cfg.get('subtitle_sync', True))


def get_alist_download_url(config: dict, alist_path: str) -> tuple:
    """构造 AList 代理下载 URL，返回 (url, sign) 元组。

    使用 AList 自身的代理下载接口 /d/<path>，让 AList 持有的
    云盘凭证（如 115 Cookie）来完成实际下载，避免直接请求云盘的 403。

    Returns:
        (download_url, sign) 元组
    """
    from urllib.parse import quote
    base_url = (config.get('alist', {}) or {}).get('base_url', '').rstrip('/')
    data = alist_request(config, '/api/fs/get', {
        'path': alist_path,
        'password': '',
    })
    sign = (data.get('data') or {}).get('sign') or ''
    # 对路径做 URL 编码：空格→%20，保留 / 分隔符
    encoded_path = quote(alist_path, safe='/')
    url = f"{base_url}/d{encoded_path}"
    return url, sign


def download_file(url: str, dest: Path, token: str = '', sign: str = '', timeout: int = 120):
    """通过 AList 代理接口下载文件到本地路径。

    同时通过 Header 和 query 参数传递 Token/Sign，
    兼容所有 AList 认证模式。

    Args:
        url: AList 代理下载 URL（/d/<path>）
        dest: 本地目标路径
        token: AList Token
        sign: AList 文件签名
        timeout: 超时秒数（字幕文件较小，120s 够用）
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 构造带认证信息的完整 URL（query 参数方式，对值做编码）
    from urllib.parse import quote as _quote
    params = []
    if sign:
        params.append(f'sign={_quote(sign, safe="")}')
    if token:
        params.append(f'token={_quote(token, safe="")}')
    full_url = f"{url}?{'&'.join(params)}" if params else url

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    if token:
        headers['Authorization'] = token

    print(f'[字幕] 请求 URL: {url}（sign={bool(sign)}, token={bool(token)}）', flush=True)
    req = request.Request(full_url, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get('Content-Type', '')
            data = resp.read()
        # 如果返回的是 JSON（通常是 AList 错误响应），说明下载失败
        if 'application/json' in content_type:
            raise RuntimeError(f'AList 返回 JSON 而非文件内容，可能是权限问题: {data[:200].decode("utf-8", "ignore")}')
        dest.write_bytes(data)
    except error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'ignore')[:300]
        except Exception:
            pass
        raise RuntimeError(f'HTTP {e.code} ({e.reason}) URL={url} 响应={body}')
    except Exception as e:
        raise RuntimeError(f'下载异常: {url} — {e}')


def sync_subtitles(
    config: dict,
    subtitle_files: List[str],
    output_root: str,
    scan_path: str,
    output_prefix: str,
) -> Dict[str, int]:
    """将 AList 中的字幕文件同步到服务器本地。

    Args:
        config: 配置字典
        subtitle_files: AList 字幕文件路径列表
        output_root: 服务器本地 .strm 输出根目录（如 /emby-strm）
        scan_path: AList 扫描根路径（如 /115/电影）
        output_prefix: 输出逻辑前缀（如 /115/电影）

    Returns:
        统计字典：{downloaded, skipped_existing, failed}
    """
    stats = {'downloaded': 0, 'skipped_existing': 0, 'failed': 0}

    if not subtitle_files:
        return stats

    token = (config.get('alist', {}) or {}).get('token', '')

    for full_path in subtitle_files:
        # 计算逻辑路径（与媒体文件映射逻辑完全一致）
        media_path = map_scan_to_media(scan_path, output_prefix, full_path)
        # 目标本地路径（保持原扩展名，不转换为 .strm）
        relative = media_path.lstrip('/')
        dest = Path(output_root) / relative

        if dest.exists():
            stats['skipped_existing'] += 1
            continue

        try:
            download_url, sign = get_alist_download_url(config, full_path)
            download_file(download_url, dest, token=token, sign=sign)
            print(f'[字幕] 已下载: {dest}')
            stats['downloaded'] += 1
            # 下载后短暂延迟，避免触发限速
            time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            print(f'[字幕] 下载失败: {full_path} — {e}', flush=True)
            stats['failed'] += 1

    return stats
