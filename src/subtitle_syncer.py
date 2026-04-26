"""字幕文件同步模块 - 从 AList 下载字幕到服务器本地对应目录。"""
import time
import random
from pathlib import Path
from typing import Dict, List
from urllib import request, error

from .alist_client import alist_request
from .generator import map_scan_to_media


def get_subtitle_exts(config: dict) -> set:
    """从配置中获取字幕扩展名集合，回退到内置默认值。

    Args:
        config: 配置字典

    Returns:
        字幕扩展名集合（小写，带点前缀）
    """
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
    """判断字幕同步功能是否启用（默认 True）。

    Args:
        config: 配置字典

    Returns:
        True 表示启用字幕同步
    """
    scan_cfg = config.get('scan') or {}
    return bool(scan_cfg.get('subtitle_sync', True))


def get_alist_file_raw_url(config: dict, alist_path: str) -> str:
    """通过 AList /api/fs/get 获取文件直链 URL。

    Args:
        config: 配置字典（含 alist.base_url / alist.token）
        alist_path: AList 文件路径（如 /115/电影/XXX/subtitle.srt）

    Returns:
        文件直链 URL

    Raises:
        RuntimeError: 当 AList 返回错误或无直链时
    """
    data = alist_request(config, '/api/fs/get', {
        'path': alist_path,
        'password': '',
    })
    raw_url = (data.get('data') or {}).get('raw_url') or ''
    if not raw_url:
        raise RuntimeError(f'AList 未返回直链: {alist_path}')
    return raw_url


def download_file(url: str, dest: Path, timeout: int = 60):
    """通过 HTTP 下载文件到本地路径。

    Args:
        url: 文件直链 URL
        dest: 本地目标路径
        timeout: 超时秒数
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = request.Request(url, headers={'User-Agent': 'xstrm-subtitle-syncer/1.0'})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        dest.write_bytes(data)
    except error.HTTPError as e:
        raise RuntimeError(f'下载字幕 HTTP {e.code}: {url}')
    except Exception as e:
        raise RuntimeError(f'下载字幕失败: {url} — {e}')


def sync_subtitles(
    config: dict,
    subtitle_files: List[str],
    output_root: str,
    scan_path: str,
    output_prefix: str,
) -> Dict[str, int]:
    """将 AList 中的字幕文件同步到服务器本地。

    每个字幕文件路径通过与媒体文件相同的映射规则得到目标路径：
    AList 路径 → 逻辑媒体路径 → 本地 output_root 下的同名文件（保持原扩展名）。

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
            raw_url = get_alist_file_raw_url(config, full_path)
            download_file(raw_url, dest)
            print(f'[字幕] 已下载: {dest}')
            stats['downloaded'] += 1
            # 下载后短暂延迟，避免触发限速
            time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            print(f'[字幕] 下载失败: {full_path} — {e}', flush=True)
            stats['failed'] += 1

    return stats
